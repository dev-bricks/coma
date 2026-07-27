"""Der Statusschreiber — **einziger** Schreiber von ``coma.<jobid>.json``.

Vorlage: ``_control-center/_agentjobs/coma_status.py``. Die Schluessel sind
zeichengleich uebernommen (``job_id``, ``state``, ``model``, ``started``,
``finished``, ``job_file``, ``result_file``, ``exit_code``), damit die bestehende
Startschale und diese Python-Schicht dieselbe Datei lesen und schreiben koennen.

Zwei Aenderungen gegenueber der Vorlage, beide bewusst:

1. **Geschrieben wird atomar** (Temp-Datei + ``os.replace``). Die Vorlage schrieb
   direkt in die Zieldatei; ein Abbruch mitten im Schreiben haette eine halbe
   JSON-Datei hinterlassen — genau die Sorte stiller Tod, die ``KONZEPT.md``
   Lektion 3 ausschliessen will.
2. ``extra`` erlaubt additive Felder (z. B. ``argv``, ``adapter``). Additiv, weil
   ``finish`` die vorhandene Datei laedt und unbekannte Schluessel erhaelt — die
   Kompatibilitaet gilt damit in beide Richtungen.

Das Modul bleibt ausserdem als Skript aufrufbar und argv-kompatibel zur Vorlage::

    python -m coma.status start  <comafile> <jobid> <model> <jobfile> <resultfile>
    python -m coma.status finish <comafile> <exitcode>
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"

#: Die Schluessel der Vorlage, in ihrer Reihenfolge.
BASE_KEYS: tuple[str, ...] = (
    "job_id",
    "state",
    "model",
    "started",
    "finished",
    "job_file",
    "result_file",
    "exit_code",
)


def now() -> str:
    """Zeitstempel im Format der Vorlage (``coma_status.py:18-19``)."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def write_json(path: str | os.PathLike[str], data: Mapping[str, Any]) -> None:
    """JSON atomar schreiben: erst daneben, dann an die Stelle schieben."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, target)


def read_json(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Statusdatei lesen. ``None``, wenn sie fehlt oder unlesbar ist."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class StatusWriter:
    """Schreibt den Status **eines** Jobs. Genau eine Instanz je Job.

    Wer diese Klasse benutzt, uebernimmt damit die Rolle „Runner" im Protokoll.
    Kein anderer Beteiligter darf in diese Datei schreiben.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def __repr__(self) -> str:  # pragma: no cover - Komfort
        return f"<StatusWriter path={str(self.path)!r}>"

    def start(
        self,
        job_id: str,
        model: str,
        job_file: str | os.PathLike[str],
        result_file: str | os.PathLike[str],
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "job_id": job_id,
            "state": STATE_RUNNING,
            "model": model,
            "started": now(),
            "finished": None,
            "job_file": str(job_file),
            "result_file": str(result_file),
            "exit_code": None,
        }
        if extra:
            data.update(extra)
        write_json(self.path, data)
        return data

    def finish(
        self, exit_code: int, *, extra: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Lauf abschliessen. Vorhandene Felder bleiben erhalten.

        Fehlt die Datei, wird ein Minimaleintrag geschrieben — so wie in der
        Vorlage (``coma_status.py:43-47``). Der Zustand darf nie ganz fehlen.
        """
        data = read_json(self.path) or {"job_id": None}
        code = int(exit_code)
        data["state"] = STATE_DONE if code == 0 else STATE_FAILED
        data["exit_code"] = code
        data["finished"] = now()
        if extra:
            data.update(extra)
        write_json(self.path, data)
        return data

    def read(self) -> dict[str, Any] | None:
        return read_json(self.path)


def main(argv: list[str] | None = None) -> int:
    """Argv-kompatibler Einstieg zur Vorlage ``coma_status.py``."""
    argv = sys.argv if argv is None else argv
    if len(argv) < 3:
        print("usage: coma.status start|finish <comafile> ...", file=sys.stderr)
        return 2
    mode, path = argv[1], argv[2]
    writer = StatusWriter(path)
    if mode == "start":
        if len(argv) < 7:
            print(
                "usage: coma.status start <comafile> <jobid> <model> "
                "<jobfile> <resultfile>",
                file=sys.stderr,
            )
            return 2
        writer.start(argv[3], argv[4], argv[5], argv[6])
    elif mode == "finish":
        if len(argv) < 4:
            print("usage: coma.status finish <comafile> <exitcode>", file=sys.stderr)
            return 2
        writer.finish(int(argv[3]))
    else:
        print(f"unbekannter Modus: {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - Skripteinstieg
    raise SystemExit(main(sys.argv))
