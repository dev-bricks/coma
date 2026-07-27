"""Der Job-Runner: Protokoll, Status und Spawn zu einem Lauf verbunden.

Das ist ``START-LOCAL-AGENT.bat`` batch-frei in Python — Schritt fuer Schritt in
derselben Reihenfolge, damit beide Wege dieselben Artefakte hinterlassen:

1. Job-ID aufloesen (ohne Angabe: aeltester Auftrag in ``IN/``) — ``.bat:36-43``
2. Verzeichnisse anlegen — ``.bat:56-57``
3. ``to-agent.jsonl`` leer anlegen — ``.bat:58``
4. Status auf ``running`` — ``.bat:60``
5. Agent starten, stdout und stderr in ``coma.<jobid>.console.log`` — ``.bat:72``
6. Status auf ``done``/``failed`` mit Exitcode — ``.bat:75``
7. Bei Exitcode 0: Auftrag nach ``DONE/`` verschieben; sonst bleibt er in ``IN/``
   liegen, damit nichts still verloren geht — ``.bat:77-83``

Was in Python besser ist als in der ``.bat``: Der Prompt geht als eigenes
Argument an ``subprocess`` und wird von keiner Shell erneut geparst. Die
Quoting-Falle aus ``KONZEPT.md`` Lektion 1 (ein eingebettetes ``\\"`` zerriss den
Befehl still) kann hier nicht zuschlagen. Die Regel „Anweisungen in die
Auftragsdatei, nur ein Zeiger in den Prompt" bleibt trotzdem — sie haelt die
Rueckgabe von der stdout-Groesse fern.
"""
from __future__ import annotations

import os
from typing import Any

from .adapters import DEFAULT_ADAPTER, ClaudeAdapter, CliAdapter, get_adapter
from .channels import to_agent
from .protocol import JobBoard, JobPaths
from .spawn import ProcessHandle, Spawner
from .status import StatusWriter


def _model_of(adapter: CliAdapter) -> str:
    """Das Modell eines Adapters, soweit er eines kennt (fuer die Statusdatei)."""
    model = getattr(adapter, "model", None)
    return str(model) if model else ""


def _pointer(adapter: CliAdapter, paths: JobPaths) -> str:
    """Zeiger-Prompt bauen; Adapter mit Datei-Rueckgabe brauchen den Zielpfad.

    Die Signatur wird abgefragt statt ``TypeError`` abzufangen — ein ``TypeError``
    aus dem Inneren des Adapters wuerde sonst als „nimmt nur ein Argument"
    fehlgedeutet.
    """
    import inspect

    parameters = inspect.signature(adapter.pointer_prompt).parameters
    if "result_file" in parameters:
        return adapter.pointer_prompt(paths.job_file, paths.result_file)  # type: ignore[call-arg]
    return adapter.pointer_prompt(paths.job_file)


class JobHandle:
    """Ein laufender Job. Der Status wird geschrieben, sobald jemand pollt.

    Absichtlich ohne Hintergrund-Thread: Ein Thread stirbt mit dem Elternprozess
    und liesse die Statusdatei auf ``running`` stehen — ein stiller Tod durch die
    Hintertuer. Wer nicht pollt, sieht keinen Abschluss; das ist ehrlicher als ein
    Abschluss, den niemand beobachtet hat.
    """

    def __init__(
        self,
        runner: "JobRunner",
        paths: JobPaths,
        process: ProcessHandle,
    ) -> None:
        self.runner = runner
        self.paths = paths
        self.process = process
        self._final: dict[str, Any] | None = None

    @property
    def job_id(self) -> str:
        return self.paths.job_id

    def poll(self) -> dict[str, Any] | None:
        """``None``, solange der Job laeuft; sonst das abgeschlossene Ergebnis."""
        if self._final is not None:
            return self._final
        outcome = self.process.poll()
        if outcome is None:
            return None
        self._final = self.runner.finalize(self.paths, outcome)
        return self._final

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        if self._final is not None:
            return self._final
        outcome = self.process.wait(timeout=timeout)
        self._final = self.runner.finalize(self.paths, outcome)
        return self._final

    def terminate(self) -> dict[str, Any]:
        """Abbrechen und den Abbruch im Status festhalten."""
        self.process.terminate()
        return self.wait()


class JobRunner:
    """Startet Jobs nach dem COMA-Protokoll.

    ``adapter`` bestimmt, welche CLI laeuft. Ohne Angabe der ``claude``-Adapter in
    seiner Standardkonfiguration (``dontAsk`` plus explizite Werkzeugliste).
    """

    def __init__(
        self,
        board: JobBoard | str | os.PathLike[str],
        adapter: CliAdapter | str | None = None,
        *,
        allow_unverified: bool = False,
        record_argv: bool = True,
    ) -> None:
        self.board = board if isinstance(board, JobBoard) else JobBoard(board)
        if adapter is None:
            self.adapter: CliAdapter = ClaudeAdapter()
        elif isinstance(adapter, str):
            self.adapter = get_adapter(adapter)
        else:
            self.adapter = adapter
        self.spawner = Spawner(self.adapter, allow_unverified=allow_unverified)
        self.record_argv = bool(record_argv)

    def __repr__(self) -> str:  # pragma: no cover - Komfort
        return f"<JobRunner board={str(self.board.root)!r} adapter={self.adapter.name!r}>"

    # ------------------------------------------------------------------ Schritte

    def status_writer(self, paths: JobPaths) -> StatusWriter:
        return StatusWriter(paths.status_file)

    def prepare(self, job_id: str | None = None) -> JobPaths:
        """Schritte 1-3: Job finden, Verzeichnisse anlegen, Kanal bereitstellen."""
        self.board.ensure_dirs()
        paths = self.board.resolve(job_id)
        to_agent(paths).ensure()
        return paths

    def _announce(self, paths: JobPaths, argv: list[str]) -> None:
        """Schritt 4: Status auf ``running``, mit dem Kommando als Beleg."""
        extra: dict[str, Any] = {"adapter": self.adapter.name}
        if self.record_argv:
            extra["argv"] = argv
            extra["console_log"] = str(paths.console_log)
        self.status_writer(paths).start(
            paths.job_id,
            _model_of(self.adapter),
            paths.job_file,
            paths.result_file,
            extra=extra,
        )

    def finalize(self, paths: JobPaths, outcome: dict[str, Any]) -> dict[str, Any]:
        """Schritte 6-7: Status abschliessen, bei Erfolg archivieren.

        Idempotent: ein zweiter Aufruf schreibt denselben Zustand und archiviert
        nicht doppelt (der Auftrag liegt dann nicht mehr in ``IN/``).
        """
        returncode = int(outcome.get("returncode", -3))
        status = self.status_writer(paths).finish(returncode)
        archived = None
        if returncode == 0 and paths.job_file.is_file():
            archived = str(self.board.archive(paths.job_id))
        elif paths.done_file.is_file():
            archived = str(paths.done_file)
        return {
            **outcome,
            "job_id": paths.job_id,
            "status": status,
            "archived": archived,
            "result_file": str(paths.result_file),
            "result_written": paths.result_file.is_file(),
            "paths": paths.as_dict(),
        }

    # -------------------------------------------------------------------- Laeufe

    def run(self, job_id: str | None = None, **overrides: Any) -> dict[str, Any]:
        """Einen Job blockierend abarbeiten."""
        paths = self.prepare(job_id)
        prompt = overrides.pop("prompt", None) or _pointer(self.adapter, paths)
        spec = self.adapter.build_spec(
            prompt, result_file=paths.result_file, **overrides
        )
        self._announce(paths, list(spec.argv))
        outcome = self.spawner.run_spec(spec, log_file=paths.console_log)
        return self.finalize(paths, outcome)

    def start(self, job_id: str | None = None, **overrides: Any) -> JobHandle:
        """Einen Job starten und sofort zurueckkehren.

        Der Aufrufer muss ``poll()`` oder ``wait()`` benutzen, sonst bleibt der
        Status auf ``running`` stehen.
        """
        paths = self.prepare(job_id)
        prompt = overrides.pop("prompt", None) or _pointer(self.adapter, paths)
        spec = self.adapter.build_spec(
            prompt, result_file=paths.result_file, **overrides
        )
        self._announce(paths, list(spec.argv))
        process = self.spawner.start_spec(spec, log_file=paths.console_log)
        return JobHandle(self, paths, process)

    def dry_run(self, job_id: str | None = None, **overrides: Any) -> dict[str, Any]:
        """Alles bauen, nichts starten — der Bauplan als Ergebnis.

        Damit laesst sich pruefen, welches Kommando ein Job ausloesen wuerde,
        bevor Tokens fliessen.
        """
        paths = self.board.resolve(job_id)
        prompt = overrides.pop("prompt", None) or _pointer(self.adapter, paths)
        spec = self.adapter.build_spec(
            prompt, result_file=paths.result_file, **overrides
        )
        return {
            "job_id": paths.job_id,
            "adapter": spec.adapter,
            "verified": spec.verified,
            "argv": list(spec.argv),
            "rendered": spec.rendered(),
            "executable": spec.executable,
            "cwd": spec.cwd,
            "timeout": spec.timeout,
            "paths": paths.as_dict(),
        }


__all__ = ["DEFAULT_ADAPTER", "JobHandle", "JobRunner"]
