"""Prozesse starten und in Kontakt bleiben — das ``spawn``-Verb von COMAS.

Der Spawner kennt keine CLI. Er nimmt eine :class:`~comas.adapters.base.SpawnSpec`
und startet sie. Alles anbieterspezifische steckt im Adapter.

Herkunft: ``subprocess.run``-Aufruf, Timeout- und Fehlerbehandlung extrahiert aus
``llmauto/core/runner.py:53-117`` und ``swarm-ai/tools/runner.py:101-226``
(dort auch ``run_parallel``); die Nebenlaeufigkeits-Begrenzung entspricht der
Semaphore in ``swarm-ai/experiments/dungeon/…_live.py:302``.

**Die Exitcode-Konvention des Bestands bleibt erhalten**, damit Konsumenten beim
Umhaengen nichts umschreiben muessen:

======  ============================================================
  -1    Timeout
  -2    CLI nicht gefunden
  -3    sonstiger Fehler beim Start
  -4    Fehler in einem Parallel-Worker
======  ============================================================
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .adapters.base import CliAdapter, SpawnSpec

#: Obergrenze fuer ``run_many`` (aus ``swarm-ai/tools/runner.py:187-188``).
MAX_PARALLEL_ITEMS = 100
#: Wie viel vom Konsolenlog als ``output`` zurueckgegeben wird.
DEFAULT_LOG_TAIL_BYTES = 200_000


class SpawnError(RuntimeError):
    """Der Prozess konnte nicht gestartet werden."""


class UnverifiedAdapterError(SpawnError):
    """Ein nicht live gepruefter Adapter sollte scharf gestartet werden."""


def _now() -> datetime:
    return datetime.now()


def _read_tail(path: Path, limit: int = DEFAULT_LOG_TAIL_BYTES) -> str:
    """Das Ende einer Logdatei lesen — begrenzt, damit ein Riesenlog nichts sprengt."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > limit:
                handle.seek(size - limit)
            data = handle.read()
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace").strip()


class ProcessHandle:
    """Ein laufender Prozess, den man beobachten kann, ohne auf ihn zu warten.

    Das ist die Haelfte von COMAS, die ueber ein bloss synchrones
    ``subprocess.run`` hinausgeht: Ein Orchestrator will **wissen**, wie es steht,
    ohne zu blockieren.
    """

    def __init__(
        self,
        spec: SpawnSpec,
        popen: "subprocess.Popen[Any]",
        *,
        log_file: Path | None = None,
        log_handle: Any = None,
        timeout: int | None = None,
    ) -> None:
        self.spec = spec
        self.popen = popen
        self.log_file = log_file
        self._log_handle = log_handle
        self.timeout = timeout
        self.started_at = _now()
        self._result: dict[str, Any] | None = None

    @property
    def pid(self) -> int:
        return self.popen.pid

    @property
    def duration_s(self) -> float:
        return (_now() - self.started_at).total_seconds()

    def poll(self) -> dict[str, Any] | None:
        """``None``, solange der Prozess laeuft; sonst das Ergebnis.

        Beim ersten beobachteten Ende wird das Ergebnis gebildet und gemerkt —
        weitere Aufrufe liefern denselben Wert.
        """
        if self._result is not None:
            return self._result
        code = self.popen.poll()
        if code is None:
            if self.timeout is not None and self.duration_s > self.timeout:
                self.terminate()
                self._result = self._build_result(-1, timed_out=True)
                return self._result
            return None
        self._result = self._build_result(code)
        return self._result

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        """Blockierend warten. ``timeout`` ueberschreibt den des Specs."""
        if self._result is not None:
            return self._result
        limit = self.timeout if timeout is None else timeout
        try:
            code = self.popen.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            self.terminate()
            self._result = self._build_result(-1, timed_out=True)
            return self._result
        self._result = self._build_result(code)
        return self._result

    def terminate(self) -> None:
        """Beenden, notfalls hart. Danach ist der Prozess sicher weg."""
        if self.popen.poll() is None:
            self.popen.terminate()
            try:
                self.popen.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - Notausgang
                self.popen.kill()
                self.popen.wait(timeout=10)

    def _close_log(self) -> None:
        if self._log_handle is not None:
            try:
                self._log_handle.close()
            finally:
                self._log_handle = None

    def _build_result(self, returncode: int, *, timed_out: bool = False) -> dict[str, Any]:
        self._close_log()
        duration = self.duration_s
        output = ""
        stderr = ""
        if self.log_file is not None:
            output = _read_tail(Path(self.log_file))
        else:  # pragma: no cover - Popen ohne Log wird nicht genutzt
            output = ""
        if timed_out:
            stderr = f"TIMEOUT nach {self.timeout}s"
        return build_result(
            self.spec,
            returncode=returncode,
            output=output,
            stderr=stderr,
            duration_s=duration,
            timed_out=timed_out,
            log_file=self.log_file,
        )


def build_result(
    spec: SpawnSpec,
    *,
    returncode: int,
    output: str = "",
    stderr: str = "",
    duration_s: float = 0.0,
    timed_out: bool = False,
    log_file: Path | str | None = None,
) -> dict[str, Any]:
    """Das Ergebnis-Dict bauen.

    Die Schluessel ``success``, ``output``, ``stderr``, ``returncode``,
    ``duration_s`` und ``model`` sind zeichengleich mit dem Bestand
    (``llmauto/core/runner.py:78-85``), damit ein Konsument beim Umhaengen nichts
    anpassen muss. ``argv``, ``adapter``, ``timed_out`` und ``log_file`` kommen
    additiv hinzu.
    """
    model = ""
    argv = list(spec.argv)
    if "--model" in argv:
        index = argv.index("--model")
        if index + 1 < len(argv):
            model = argv[index + 1]
    return {
        "success": returncode == 0,
        "output": output,
        "stderr": stderr,
        "returncode": returncode,
        "duration_s": duration_s,
        "model": model,
        "adapter": spec.adapter,
        "argv": argv,
        "timed_out": timed_out,
        "log_file": None if log_file is None else str(log_file),
    }


class Spawner:
    """Startet Prozesse nach dem Bauplan eines Adapters.

    ``allow_unverified`` ist die Sicherung gegen einen ungetesteten Aufrufweg in
    einem unbeaufsichtigten Lauf: Solange sie nicht gesetzt ist, verweigert der
    Spawner jeden Adapter mit ``verified = False``.
    """

    def __init__(
        self,
        adapter: CliAdapter,
        *,
        allow_unverified: bool = False,
        log_tail_bytes: int = DEFAULT_LOG_TAIL_BYTES,
    ) -> None:
        self.adapter = adapter
        self.allow_unverified = bool(allow_unverified)
        self.log_tail_bytes = int(log_tail_bytes)

    # ------------------------------------------------------------------ Pruefung

    def _guard(self, spec: SpawnSpec) -> None:
        if not spec.verified and not self.allow_unverified:
            raise UnverifiedAdapterError(
                f"Adapter {spec.adapter!r} ist nicht live geprueft. "
                "Zum Starten ausdruecklich allow_unverified=True setzen."
            )

    # -------------------------------------------------------------- synchron

    def run(self, prompt: str, **overrides: Any) -> dict[str, Any]:
        """Kommando bauen und blockierend ausfuehren."""
        log_file = overrides.pop("log_file", None)
        spec = self.adapter.build_spec(prompt, **overrides)
        return self.run_spec(spec, log_file=log_file)

    def run_spec(
        self, spec: SpawnSpec, *, log_file: Path | str | None = None
    ) -> dict[str, Any]:
        """Einen fertigen Bauplan ausfuehren.

        Getrennt von :meth:`run`, weil ein Orchestrator den Bauplan **vor** dem
        Start protokollieren will (COMAS schreibt ihn in die Statusdatei).

        Ist ``log_file`` gesetzt, gehen stdout und stderr zusammen in diese Datei
        — das Python-Gegenstueck zu ``> log 2>&1``. ``KONZEPT.md`` Lektion 3: ein
        stiller Tod darf nicht moeglich sein. Danach wird das Ende der Datei als
        ``output`` zurueckgelesen, damit der Aufrufer trotzdem etwas in der Hand
        hat.
        """
        self._guard(spec)
        start = _now()
        kwargs: dict[str, Any] = {
            "env": dict(spec.env),
            "timeout": spec.timeout,
            "cwd": spec.cwd,
        }
        handle = None
        try:
            if log_file is not None:
                path = Path(log_file)
                path.parent.mkdir(parents=True, exist_ok=True)
                handle = path.open("wb")
                completed = subprocess.run(
                    spec.command, stdout=handle, stderr=subprocess.STDOUT, **kwargs
                )
                handle.close()
                handle = None
                return build_result(
                    spec,
                    returncode=completed.returncode,
                    output=_read_tail(path, self.log_tail_bytes),
                    duration_s=(_now() - start).total_seconds(),
                    log_file=path,
                )
            completed = subprocess.run(
                spec.command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **kwargs,
            )
            return build_result(
                spec,
                returncode=completed.returncode,
                output=(completed.stdout or "").strip(),
                stderr=(completed.stderr or "").strip(),
                duration_s=(_now() - start).total_seconds(),
            )

        except subprocess.TimeoutExpired:
            return build_result(
                spec,
                returncode=-1,
                stderr=f"TIMEOUT nach {spec.timeout}s",
                duration_s=(_now() - start).total_seconds(),
                timed_out=True,
                log_file=log_file,
            )
        except FileNotFoundError:
            return build_result(
                spec,
                returncode=-2,
                stderr=(
                    f"{spec.argv[0]} nicht gefunden. Ist die CLI installiert "
                    "und im PATH?"
                ),
                log_file=log_file,
            )
        except OSError as error:
            return build_result(
                spec,
                returncode=-3,
                stderr=str(error),
                duration_s=(_now() - start).total_seconds(),
                log_file=log_file,
            )
        finally:
            if handle is not None:
                handle.close()

    # ------------------------------------------------------------ nicht-blockierend

    def start(
        self, prompt: str, *, log_file: Path | str | None = None, **overrides: Any
    ) -> ProcessHandle:
        """Prozess starten und sofort zurueckkehren."""
        spec = self.adapter.build_spec(prompt, **overrides)
        return self.start_spec(spec, log_file=log_file)

    def start_spec(
        self, spec: SpawnSpec, *, log_file: Path | str | None = None
    ) -> ProcessHandle:
        """Einen fertigen Bauplan starten und einen :class:`ProcessHandle` liefern.

        Der Aufrufer muss ``poll()`` oder ``wait()`` benutzen — nur dort wird das
        Ergebnis gebildet. Absichtlich ohne Hintergrund-Thread: ein Thread stirbt
        mit dem Elternprozess und wuerde eine Statusdatei auf ``running`` stehen
        lassen. Ohne Thread ist der Zustand immer der, den jemand beobachtet hat.
        """
        self._guard(spec)
        handle = None
        stdout: Any = subprocess.DEVNULL
        path: Path | None = None
        if log_file is not None:
            path = Path(log_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("wb")
            stdout = handle
        try:
            popen = subprocess.Popen(
                spec.command,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                env=dict(spec.env),
                cwd=spec.cwd,
            )
        except (OSError, ValueError) as error:
            if handle is not None:
                handle.close()
            raise SpawnError(f"Start von {spec.argv[0]!r} fehlgeschlagen: {error}") from error
        return ProcessHandle(
            spec, popen, log_file=path, log_handle=handle, timeout=spec.timeout
        )

    # -------------------------------------------------------------- parallel

    def run_many(
        self,
        items: Iterable[str | Mapping[str, Any]],
        *,
        max_parallel: int = 3,
        **overrides: Any,
    ) -> list[dict[str, Any]]:
        """Mehrere Aufrufe nebenlaeufig ausfuehren, Reihenfolge bleibt erhalten.

        ``items`` sind Prompt-Strings oder Dicts mit ``{"prompt": …, **overrides}``.
        Uebernommen aus ``swarm-ai/tools/runner.py:169-226``; die Begrenzung
        ersetzt die dortige ``threading.Semaphore``.
        """
        from concurrent.futures import ThreadPoolExecutor

        if max_parallel <= 0:
            raise ValueError("max_parallel muss groesser als null sein")
        if isinstance(items, (str, bytes)):
            raise TypeError(
                "items muss eine Sequenz von Prompts sein, kein String"
            )
        tasks: list[tuple[str, dict[str, Any]]] = []
        for item in items:
            if isinstance(item, Mapping):
                merged = {**overrides, **dict(item)}
                if "prompt" not in merged:
                    raise ValueError("Dict-Eintraege brauchen einen 'prompt'-Schluessel")
                prompt = merged.pop("prompt")
            else:
                prompt, merged = item, dict(overrides)
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError("jeder Prompt muss ein nicht-leerer String sein")
            tasks.append((prompt, merged))
        if len(tasks) > MAX_PARALLEL_ITEMS:
            raise ValueError(
                f"hoechstens {MAX_PARALLEL_ITEMS} Prompts je Parallel-Lauf"
            )

        results: list[dict[str, Any]] = [
            build_result(
                SpawnSpec(adapter=self.adapter.name, argv=("<nicht gestartet>",), env={}),
                returncode=-4,
                stderr="Worker hat kein Ergebnis geliefert",
            )
            for _ in tasks
        ]
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {
                pool.submit(self.run, prompt, **task_overrides): index
                for index, (prompt, task_overrides) in enumerate(tasks)
            }
            for future, index in futures.items():
                try:
                    results[index] = future.result()
                except Exception as error:  # noqa: BLE001 - ein Worker darf den Lauf nicht kippen
                    results[index] = build_result(
                        SpawnSpec(
                            adapter=self.adapter.name, argv=("<nicht gebaut>",), env={}
                        ),
                        returncode=-4,
                        stderr=str(error),
                    )
        return results

    def pipe(self, prompt: str, **overrides: Any) -> str:
        """Kurzform: Prompt rein, Text raus. Wirft bei Fehler.

        Aus ``llmauto/core/runner.py:119-124``. Fehlermeldung dort auf Deutsch —
        bleibt so, damit bestehende Aufrufer, die auf den Text pruefen, nicht
        brechen.
        """
        result = self.run(prompt, **overrides)
        if not result["success"]:
            raise RuntimeError(
                f"Claude Fehler (rc={result['returncode']}): {result['stderr']}"
            )
        return result["output"]


def wait_all(handles: Sequence[ProcessHandle], *, interval: float = 1.0) -> list[dict[str, Any]]:
    """Auf mehrere Handles warten, indem regelmaessig gepollt wird."""
    pending = list(handles)
    results: dict[int, dict[str, Any]] = {}
    while pending:
        still_running = []
        for handle in pending:
            outcome = handle.poll()
            if outcome is None:
                still_running.append(handle)
            else:
                results[id(handle)] = outcome
        pending = still_running
        if pending:
            time.sleep(interval)
    return [results[id(handle)] for handle in handles]
