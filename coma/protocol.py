"""Das COMA-Protokoll: Verzeichnis- und Dateikonvention.

::

    IN/    <jobid>.md                       Auftrag (Freitext-Markdown)
    OUT/   <jobid>.result.md                Ergebnis
           coma.<jobid>.json               Status      — nur der Runner schreibt
           coma.<jobid>.from-agent.jsonl   Fortschritt — nur der Agent schreibt
           coma.<jobid>.to-agent.jsonl     Nachrichten — nur der Orchestrator schreibt
           coma.<jobid>.console.log        stdout/stderr des Laufs
    DONE/  <jobid>.md                       erledigter Auftrag

**Ein Schreiber je Datei — kein Locking noetig, Kollision strukturell
unmoeglich.** Gelesen werden darf von allen. Das ist keine Vorsichtsmassnahme,
sondern eine Lektion: eine geteilte Logdatei in OneDrive hat schon zu
Konfliktkopien gefuehrt (Ticket ``T-20260621-44``).

Die Namen sind zeichengenau die der Referenzimplementierung
(``START-LOCAL-AGENT.bat:46-49,58``), damit die Python-Schicht und die bestehende
Startschale dieselben Artefakte lesen und schreiben.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

#: Erlaubte Job-IDs. Bewusst eng: eine Job-ID wird zu einem Dateinamen, und ein
#: ``..`` oder Pfadtrenner darin wuerde aus dem Jobverzeichnis herausfuehren.
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

IN_DIR = "IN"
OUT_DIR = "OUT"
DONE_DIR = "DONE"


class ProtocolError(ValueError):
    """Die Anfrage passt nicht zum Protokoll."""


class JobNotFound(ProtocolError):
    """Zu dieser Job-ID liegt keine Auftragsdatei in ``IN/``."""


def check_job_id(job_id: str) -> str:
    """Job-ID pruefen. Wirft, statt einen kaputten Dateinamen zu bauen."""
    if not isinstance(job_id, str) or not JOB_ID_PATTERN.match(job_id):
        raise ProtocolError(
            f"unzulaessige Job-ID {job_id!r} — erlaubt sind Buchstaben, Ziffern, "
            "Punkt, Bindestrich und Unterstrich, beginnend alphanumerisch"
        )
    if job_id.endswith(".md"):
        raise ProtocolError(
            f"Job-ID {job_id!r} enthaelt die Endung — die Job-ID ist der "
            "Dateiname ohne .md"
        )
    return job_id


@dataclass(frozen=True)
class JobPaths:
    """Alle Pfade eines Jobs an einer Stelle."""

    root: Path
    job_id: str

    @property
    def in_dir(self) -> Path:
        return self.root / IN_DIR

    @property
    def out_dir(self) -> Path:
        return self.root / OUT_DIR

    @property
    def done_dir(self) -> Path:
        return self.root / DONE_DIR

    @property
    def job_file(self) -> Path:
        return self.in_dir / f"{self.job_id}.md"

    @property
    def done_file(self) -> Path:
        return self.done_dir / f"{self.job_id}.md"

    @property
    def result_file(self) -> Path:
        return self.out_dir / f"{self.job_id}.result.md"

    @property
    def status_file(self) -> Path:
        return self.out_dir / f"coma.{self.job_id}.json"

    @property
    def from_agent_file(self) -> Path:
        return self.out_dir / f"coma.{self.job_id}.from-agent.jsonl"

    @property
    def to_agent_file(self) -> Path:
        return self.out_dir / f"coma.{self.job_id}.to-agent.jsonl"

    @property
    def console_log(self) -> Path:
        return self.out_dir / f"coma.{self.job_id}.console.log"

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "job_id": self.job_id,
            "job_file": str(self.job_file),
            "result_file": str(self.result_file),
            "status_file": str(self.status_file),
            "from_agent_file": str(self.from_agent_file),
            "to_agent_file": str(self.to_agent_file),
            "console_log": str(self.console_log),
            "done_file": str(self.done_file),
        }


class JobBoard:
    """Das Jobverzeichnis als Objekt: einreichen, finden, archivieren.

    Das Brett kennt keinen Agenten und startet nichts — es verwaltet nur die
    Dateien des Protokolls.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def __repr__(self) -> str:  # pragma: no cover - Komfort
        return f"<JobBoard root={str(self.root)!r}>"

    def ensure_dirs(self) -> None:
        for path in (self.root / IN_DIR, self.root / OUT_DIR, self.root / DONE_DIR):
            path.mkdir(parents=True, exist_ok=True)

    def paths(self, job_id: str) -> JobPaths:
        return JobPaths(self.root, check_job_id(job_id))

    # ------------------------------------------------------------------ Eingang

    def submit(
        self, job_id: str, markdown: str, *, overwrite: bool = False
    ) -> JobPaths:
        """Einen Auftrag als ``IN/<jobid>.md`` ablegen."""
        paths = self.paths(job_id)
        self.ensure_dirs()
        if paths.job_file.exists() and not overwrite:
            raise ProtocolError(
                f"Auftragsdatei existiert bereits: {paths.job_file} "
                "(overwrite=True erzwingt das Ueberschreiben)"
            )
        paths.job_file.write_text(markdown, encoding="utf-8", newline="\n")
        return paths

    def pending(self) -> list[str]:
        """Offene Job-IDs, aelteste zuerst.

        Sortiert nach Aenderungszeit — dieselbe Reihenfolge wie ``dir /b /o:d``
        in ``START-LOCAL-AGENT.bat:37``. Bei gleicher Zeit nach Name, damit die
        Reihenfolge reproduzierbar bleibt.
        """
        in_dir = self.root / IN_DIR
        if not in_dir.is_dir():
            return []
        entries = []
        for path in in_dir.glob("*.md"):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:  # pragma: no cover - Datei verschwand zwischendurch
                continue
            entries.append((mtime, path.stem))
        return [stem for _, stem in sorted(entries)]

    def oldest_pending(self) -> str | None:
        jobs = self.pending()
        return jobs[0] if jobs else None

    def resolve(self, job_id: str | None) -> JobPaths:
        """Job-ID aufloesen; ``None`` nimmt den aeltesten offenen Auftrag."""
        if job_id is None:
            oldest = self.oldest_pending()
            if oldest is None:
                raise JobNotFound(f"keine Auftraege in {self.root / IN_DIR}")
            job_id = oldest
        paths = self.paths(job_id)
        if not paths.job_file.is_file():
            raise JobNotFound(f"Auftragsdatei nicht gefunden: {paths.job_file}")
        return paths

    # ----------------------------------------------------------------- Ausgang

    def archive(self, job_id: str) -> Path:
        """``IN/<jobid>.md`` nach ``DONE/`` verschieben.

        ``os.replace`` statt ``shutil.move``: atomar und ueberschreibt eine
        vorhandene Zieldatei — das Verhalten von ``move /y``
        (``START-LOCAL-AGENT.bat:78``).
        """
        paths = self.paths(job_id)
        paths.done_dir.mkdir(parents=True, exist_ok=True)
        if not paths.job_file.is_file():
            raise JobNotFound(f"nichts zu archivieren: {paths.job_file}")
        os.replace(paths.job_file, paths.done_file)
        return paths.done_file

    def done(self) -> list[str]:
        done_dir = self.root / DONE_DIR
        if not done_dir.is_dir():
            return []
        return sorted(path.stem for path in done_dir.glob("*.md") if path.is_file())

    def known_jobs(self) -> list[str]:
        """Alle Job-IDs, zu denen es irgendein Artefakt gibt."""
        jobs = set(self.pending()) | set(self.done())
        out_dir = self.root / OUT_DIR
        if out_dir.is_dir():
            for path in out_dir.glob("coma.*.json"):
                jobs.add(path.name[len("coma.") : -len(".json")])
        return sorted(jobs)
