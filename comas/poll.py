"""Poll- und Lese-Hilfen fuer Orchestratoren — die Verben ``poll`` und ``result``.

Alles hier ist **nur lesend**. Ein Orchestrator darf jede Datei des Protokolls
lesen; schreiben darf er nur in ``to-agent.jsonl`` (siehe :mod:`comas.channels`).

Der Anwendungsfall, fuer den das gebaut ist: Eine Remote-Control-Session schreibt
einen Auftrag, ein lokaler Prozess arbeitet ihn ab, und die RC-Session fragt von
aussen nach dem Stand — ohne den Agenten selbst zu hosten.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from .channels import from_agent, to_agent
from .protocol import JobBoard, JobPaths
from .status import STATE_DONE, STATE_FAILED, STATE_RUNNING, read_json

#: Zustaende, in denen ein Lauf beendet ist.
FINAL_STATES = (STATE_DONE, STATE_FAILED)


def read_status(target: JobPaths | str | os.PathLike[str]) -> dict[str, Any] | None:
    """Statusdatei lesen — nimmt :class:`JobPaths` oder einen Pfad."""
    path = target.status_file if isinstance(target, JobPaths) else Path(target)
    return read_json(path)


def state(target: JobPaths | str | os.PathLike[str]) -> str | None:
    status = read_status(target)
    return None if status is None else status.get("state")


def is_running(target: JobPaths | str | os.PathLike[str]) -> bool:
    return state(target) == STATE_RUNNING


def is_finished(target: JobPaths | str | os.PathLike[str]) -> bool:
    return state(target) in FINAL_STATES


def read_result(paths: JobPaths) -> str | None:
    """Die Ergebnisdatei lesen. ``None``, wenn der Agent keine geschrieben hat."""
    if not paths.result_file.is_file():
        return None
    return paths.result_file.read_text(encoding="utf-8", errors="replace")


def read_console_log(paths: JobPaths, *, tail_bytes: int = 200_000) -> str:
    """Das Ende des Konsolenlogs lesen — die erste Adresse bei einem Fehlschlag."""
    path = paths.console_log
    if not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(size - tail_bytes)
            data = handle.read()
    except OSError:  # pragma: no cover - Datei verschwand zwischendurch
        return ""
    return data.decode("utf-8", errors="replace")


def wait_for_finish(
    paths: JobPaths,
    *,
    timeout: float | None = None,
    interval: float = 2.0,
) -> dict[str, Any]:
    """Warten, bis die Statusdatei einen Endzustand zeigt.

    Beobachtet die **Statusdatei**, nicht den Prozess — genau deshalb funktioniert
    das aus einem fremden Prozess, aus einer anderen Session oder von einem
    anderen Rechner ueber OneDrive.

    Wirft :class:`TimeoutError`, wenn die Frist verstreicht. Der Job laeuft dann
    weiter; das Warten ist abgebrochen, nicht der Lauf.
    """
    if interval <= 0:
        raise ValueError("interval muss groesser als null sein")
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        status = read_status(paths)
        if status is not None and status.get("state") in FINAL_STATES:
            return status
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"Job {paths.job_id!r} war nach {timeout}s nicht fertig "
                f"(Status: {None if status is None else status.get('state')})"
            )
        time.sleep(interval)


def job_view(paths: JobPaths) -> dict[str, Any]:
    """Ein kompakter Blick auf einen Job — fuer Uebersichten und die CLI."""
    status = read_status(paths) or {}
    return {
        "job_id": paths.job_id,
        "state": status.get("state"),
        "exit_code": status.get("exit_code"),
        "model": status.get("model"),
        "adapter": status.get("adapter"),
        "started": status.get("started"),
        "finished": status.get("finished"),
        "pending": paths.job_file.is_file(),
        "archived": paths.done_file.is_file(),
        "has_result": paths.result_file.is_file(),
        "has_log": paths.console_log.is_file(),
        "from_agent": from_agent(paths).count(),
        "to_agent": to_agent(paths).count(),
    }


def overview(board: JobBoard) -> list[dict[str, Any]]:
    """Alle bekannten Jobs eines Bretts."""
    return [job_view(board.paths(job_id)) for job_id in board.known_jobs()]
