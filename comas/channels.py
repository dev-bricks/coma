"""Die beiden Nachrichtenkanaele — das ``send``-Verb von COMAS.

``comas.<jobid>.to-agent.jsonl``     Orchestrator -> Agent (nur der Orchestrator schreibt)
``comas.<jobid>.from-agent.jsonl``   Agent -> Orchestrator (nur der Agent schreibt)

``.jsonl`` und nicht ``.json``, weil **Anhaengen atomar ist**: Ein Schreiber muss
nicht erst lesen, parsen und die ganze Datei neu schreiben. Zusammen mit „ein
Schreiber je Datei" ist damit kein Locking noetig.

Der ``role``-Parameter ist Dokumentation mit Zaehnen: Wer einen Kanal in der
falschen Rolle beschreiben will, bekommt einen Fehler statt einer Konfliktkopie.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator, Mapping

from .protocol import JobPaths
from .status import now

ROLE_ORCHESTRATOR = "orchestrator"
ROLE_AGENT = "agent"


class ChannelError(RuntimeError):
    """Ein Kanal wurde in einer Rolle benutzt, die ihm nicht gehoert."""


class Channel:
    """Ein append-only JSONL-Kanal mit genau einem zugelassenen Schreiber."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        writer_role: str,
        name: str = "",
    ) -> None:
        self.path = Path(path)
        self.writer_role = writer_role
        self.name = name or self.path.name

    def __repr__(self) -> str:  # pragma: no cover - Komfort
        return f"<Channel {self.name!r} writer={self.writer_role!r}>"

    def ensure(self) -> Path:
        """Die Datei anlegen, falls sie fehlt — ohne vorhandenen Inhalt anzutasten.

        Die Startschale legt ``to-agent.jsonl`` beim Start leer an
        (``START-LOCAL-AGENT.bat:58``), damit ein Orchestrator sofort anhaengen
        kann, ohne zu pruefen, ob die Datei schon da ist. Das bleibt so.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        return self.path

    def append(
        self, payload: Mapping[str, Any], *, role: str | None = None
    ) -> dict[str, Any]:
        """Eine Zeile anhaengen. ``ts`` wird ergaenzt, wenn es fehlt."""
        if role is not None and role != self.writer_role:
            raise ChannelError(
                f"{self.name}: nur {self.writer_role!r} darf hier schreiben, "
                f"nicht {role!r}"
            )
        if not isinstance(payload, Mapping):
            raise TypeError("payload muss ein Mapping sein")
        record = dict(payload)
        record.setdefault("ts", now())
        line = json.dumps(record, ensure_ascii=False)
        if "\n" in line:  # pragma: no cover - json.dumps escapt Zeilenumbrueche
            raise ChannelError("eine Zeile darf keinen Zeilenumbruch enthalten")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Ein einziger Schreibvorgang im Append-Modus — genau das macht
        # das Anhaengen unteilbar.
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        return record

    def read(self) -> list[dict[str, Any]]:
        """Alle gueltigen Zeilen lesen. Kaputte Zeilen werden uebersprungen.

        Uebersprungen und nicht geworfen: Ein halb geschriebener Eintrag (Absturz
        mitten im Lauf) darf einen Orchestrator nicht daran hindern, den Rest zu
        lesen.
        """
        return list(self.iter_records())

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record

    def tail(self, count: int = 10) -> list[dict[str, Any]]:
        records = self.read()
        return records[-count:] if count > 0 else []

    def since(self, index: int) -> list[dict[str, Any]]:
        """Alle Eintraege ab Position ``index`` — fuer Polling ohne Doppellesen."""
        return self.read()[max(index, 0) :]

    def count(self) -> int:
        return sum(1 for _ in self.iter_records())


def to_agent(paths: JobPaths) -> Channel:
    """Kanal Orchestrator -> Agent."""
    return Channel(
        paths.to_agent_file, writer_role=ROLE_ORCHESTRATOR, name="to-agent"
    )


def from_agent(paths: JobPaths) -> Channel:
    """Kanal Agent -> Orchestrator."""
    return Channel(paths.from_agent_file, writer_role=ROLE_AGENT, name="from-agent")
