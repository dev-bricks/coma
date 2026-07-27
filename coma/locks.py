"""Die Lock-Schnittstelle — **definiert, nicht implementiert.**

COMA sperrt nichts. Es ruft Claims ueber eine schmale Schnittstelle auf, nicht
gegen ein konkretes Modul. Dann ist der spaetere Wechsel ein Zeilenwechsel im
Stack-Manifest statt eines Umbaus:

* ``comalock`` = COMA + ``lock-master`` (lokal, offline)
* ``comaroshambo`` = COMA + Roshambo (verteilt, Cloud)

Hier steht deshalb **kein** Locking, sondern nur die Form, die ein Backend haben
muss. Es gibt in diesem Modul keinen Import von ``lock-master``, ``team-lock``
oder Roshambo — und das ist Absicht, nicht ein fehlender Schritt: COMA muss
dependency-frei und offline-faehig bleiben, das ist sein Existenzgrund
(``KONZEPT.md``, Abschnitt „Der entscheidende Trennungsgrund: Offline").

Die Signaturen folgen ``swarm-ai/tools/team_lock.py`` (``claim`` Z. 144,
``release`` Z. 165, Anwesenheit Z. 191), damit ein Adapter darauf spaeter ohne
Uebersetzungsschicht passt.

Vokabular-Grenze: COMA spricht ``spawn``, ``send``, ``poll``, ``result``. Ein
Lock-Backend spricht ``claim``, ``release``, ``status``. Keine Ueberschneidung —
haetten zwei Systeme dieselbe Aufgabe, ueberlappte ihr Vokabular.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol, runtime_checkable

#: Vorgabewert aus dem LOCK-System: ein Lock verfaellt nach 24 Stunden.
DEFAULT_TTL_SECONDS = 86400


class LockDenied(RuntimeError):
    """Der Anspruch wurde nicht gewaehrt — jemand anders haelt die Ressource."""


@runtime_checkable
class LockBackend(Protocol):
    """Was ein Lock-Backend koennen muss, damit COMA es benutzen kann.

    Ein ``Protocol``, keine Basisklasse: Ein Backend muss nichts von COMA
    importieren, um zu passen. Die Abhaengigkeit zeigt damit in keine Richtung.
    """

    def claim(
        self, resource: str, *, kind: str = "file", ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> bool:
        """Anspruch anmelden. ``True``, wenn gewaehrt."""
        ...

    def release(self, resource: str, *, kind: str = "file") -> bool:
        """Anspruch zurueckgeben. ``True``, wenn etwas freigegeben wurde."""
        ...

    def status(self, resource: str | None = None) -> Any:
        """Wer haelt gerade was? Ohne Angabe: alles Bekannte."""
        ...


class NullLock:
    """Das Standard-Backend: gewaehrt alles, merkt sich nichts.

    Damit laeuft COMA ohne jedes Lock-Modul — und ein Konsument, der spaeter ein
    echtes Backend einsetzt, aendert genau eine Zeile.
    """

    def claim(
        self, resource: str, *, kind: str = "file", ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> bool:
        return True

    def release(self, resource: str, *, kind: str = "file") -> bool:
        return True

    def status(self, resource: str | None = None) -> dict[str, Any]:
        return {"backend": "null", "held": []}


@contextmanager
def claimed(
    backend: LockBackend,
    resource: str,
    *,
    kind: str = "file",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    required: bool = True,
) -> Iterator[bool]:
    """Anspruch fuer die Dauer eines Blocks halten und danach zuverlaessig zurueckgeben.

    ``required=True`` wirft :class:`LockDenied`, wenn der Anspruch abgelehnt wird.
    Freigegeben wird auch, wenn im Block eine Ausnahme fliegt — wer sperrt, gibt
    frei; der Verfall ist nur ein Sicherheitsnetz.

    COMA ruft das **nirgends selbst auf**. Es ist die Form, in der ein
    Orchestrator einen Lauf umschliessen kann::

        with claimed(backend, "projekt/pfad", kind="project"):
            runner.run("meinjob")
    """
    granted = backend.claim(resource, kind=kind, ttl_seconds=ttl_seconds)
    if not granted and required:
        raise LockDenied(f"Anspruch auf {resource!r} ({kind}) wurde nicht gewaehrt")
    try:
        yield granted
    finally:
        if granted:
            backend.release(resource, kind=kind)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "LockBackend",
    "LockDenied",
    "NullLock",
    "claimed",
]
