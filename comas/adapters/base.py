"""Gemeinsame Basis aller CLI-Adapter.

Ein Adapter weiss genau zwei Dinge: wie das Kommando fuer seine CLI aussieht und
welche Umgebung sie braucht. Er startet **nichts** — das Starten macht
:class:`comas.spawn.Spawner`. Diese Trennung ist der Grund, warum der
Kommandobau ohne echten Prozessstart pruefbar ist.

Herkunft: extrahiert aus ``llmauto/core/runner.py`` (``_build_env`` Z. 27-32,
``_build_cmd`` Z. 34-51) und ``swarm-ai/tools/runner.py`` (Z. 41-99).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


class AdapterError(ValueError):
    """Ein Adapter kann aus den gegebenen Parametern kein Kommando bauen."""


@dataclass(frozen=True)
class SpawnSpec:
    """Alles, was zum Start eines Prozesses noetig ist — ohne ihn zu starten.

    Bewusst ein eigener, unveraenderlicher Wert: So kann ein Orchestrator das
    Kommando protokollieren, pruefen oder anzeigen, bevor irgendetwas laeuft.
    Genau das macht die Testsuite (Kommandobau gegen erwartete Argumentliste).
    """

    adapter: str
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: str | None = None
    executable: str | None = None
    verified: bool = False
    timeout: int | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def command(self) -> list[str]:
        """Die Argumentliste als ``list`` — die Form, die ``subprocess`` erwartet."""
        return list(self.argv)

    def rendered(self) -> str:
        """Menschenlesbare Einzeiler-Darstellung (nur zur Anzeige, nicht zum Ausfuehren)."""
        parts = []
        for arg in self.argv:
            parts.append(f'"{arg}"' if (not arg or " " in arg) else arg)
        return " ".join(parts)


def normalize_tool_list(value: Any, field_name: str) -> list[str]:
    """Eine Werkzeugliste pruefen und normalisieren.

    Strings werden **abgelehnt**, nicht stillschweigend zerlegt — uebernommen aus
    ``swarm-ai/tools/runner.py:61-62``. Grund: ``allowed_tools="Read"`` wuerde
    zeichenweise iteriert und ergaebe ``['R','e','a','d']``. Ein lauter Fehler ist
    hier besser als eine still falsche Werkzeugliste.
    """
    if isinstance(value, (str, bytes)):
        raise TypeError(
            f"{field_name} muss eine Sequenz von Werkzeugnamen sein, kein String "
            f"(erhalten: {value!r}). Fuer eine einzelne Angabe: [{value!r}]."
        )
    items = list(value)
    for tool in items:
        if not isinstance(tool, str) or not tool.strip():
            raise AdapterError(f"{field_name}: Eintraege muessen nicht-leere Strings sein")
    return items


class CliAdapter:
    """Basisklasse: Umgebung bauen, Kommando bauen, Zeiger-Prompt liefern.

    Unterklassen setzen ``name``, ``verified`` und implementieren ``build_cmd``.

    ``verified`` ist keine Kosmetik: :class:`comas.spawn.Spawner` weigert sich,
    einen unverifizierten Adapter zu starten, solange der Aufrufer nicht
    ausdruecklich ``allow_unverified=True`` setzt. So kann Adapterwissen
    dokumentiert und getestet werden, ohne dass ein ungetesteter Aufrufweg
    unbemerkt in einen unbeaufsichtigten Lauf geraet.
    """

    name: str = ""
    display_name: str = ""
    executable: str = ""
    verified: bool = False
    #: Merkposten, die ``comas adapters`` ausgibt — Fallstricke, Belegstellen.
    notes: tuple[str, ...] = ()
    #: Umgebungsvariablen, die vor dem Start entfernt werden.
    env_remove: tuple[str, ...] = ("CLAUDECODE",)
    default_timeout: int = 7200

    def __init__(
        self,
        *,
        executable: str | None = None,
        cwd: str | os.PathLike[str] | None = None,
        timeout: int | None = None,
        env_overrides: Mapping[str, str] | None = None,
        env_remove: Iterable[str] | None = None,
    ) -> None:
        if executable is not None:
            if not isinstance(executable, str) or not executable.strip():
                raise AdapterError("executable muss ein nicht-leerer String sein")
            self.executable = executable
        timeout = self.default_timeout if timeout is None else int(timeout)
        if timeout <= 0:
            raise AdapterError("timeout muss groesser als null sein")
        self.timeout = timeout
        self.cwd = None if cwd is None else str(cwd)
        self.env_overrides = dict(env_overrides or {})
        if env_remove is not None:
            self.env_remove = tuple(env_remove)

    # ---------------------------------------------------------------- Umgebung

    def build_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Umgebung vorbereiten: Stoervariablen entfernen, Encoding setzen.

        ``CLAUDECODE`` wird entfernt, damit sich die Kindinstanz nicht als
        verschachtelter Lauf verhaelt (Muster aus swarm-ai). Ob das ueberhaupt
        greift, ist ungeklaert — siehe ``KONZEPT.md`` Lektion 5; es schadet
        nicht, und die Referenzimplementierung lief auch ohne.

        ``PYTHONIOENCODING=utf-8`` ist auf Windows Pflicht (Konsole sonst cp1252).
        """
        env = dict(os.environ if base is None else base)
        for key in self.env_remove:
            env.pop(key, None)
        env["PYTHONIOENCODING"] = "utf-8"
        env.update(self.env_overrides)
        return env

    def resolve_executable(self) -> str | None:
        """Absoluten Pfad der CLI suchen. ``None``, wenn sie nicht im PATH liegt.

        Nur informativ — gestartet wird mit dem Namen, damit das Verhalten dem
        Bestand entspricht. Der aufgeloeste Pfad landet in der :class:`SpawnSpec`,
        damit ein Fehlschlag ("CLI nicht gefunden") vor dem Start sichtbar ist.
        """
        return shutil.which(self.executable) if self.executable else None

    # ---------------------------------------------------------------- Kommando

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        raise NotImplementedError

    def pointer_prompt(self, job_file: str | os.PathLike[str]) -> str:
        """Der kurze Prompt, der nur auf die Auftragsdatei zeigt.

        Alle Anweisungen stehen in der Datei, nicht im Prompt — ``KONZEPT.md``
        Lektion 1. Fuer jede CLI eine eigene Formulierung, weil die
        Aufrufkonventionen sich unterscheiden.
        """
        raise NotImplementedError

    def build_spec(self, prompt: str, **overrides: Any) -> SpawnSpec:
        """Kommando, Umgebung und Arbeitsverzeichnis zu einem pruefbaren Wert buendeln."""
        argv = self.build_cmd(prompt, **overrides)
        cwd = overrides.get("cwd", self.cwd)
        timeout = overrides.get("timeout", self.timeout)
        return SpawnSpec(
            adapter=self.name,
            argv=tuple(argv),
            env=self.build_env(overrides.get("env")),
            cwd=None if cwd is None else str(cwd),
            executable=self.resolve_executable(),
            verified=self.verified,
            timeout=None if timeout is None else int(timeout),
            notes=tuple(self.notes),
        )

    # ------------------------------------------------------------------ Anzeige

    def describe(self) -> dict[str, Any]:
        """Selbstauskunft fuer ``comas adapters``."""
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "executable": self.executable,
            "resolved": self.resolve_executable(),
            "verified": self.verified,
            "notes": list(self.notes),
        }

    def __repr__(self) -> str:  # pragma: no cover - Komfort
        return f"<{type(self).__name__} name={self.name!r} verified={self.verified}>"


def join_tools(tools: Sequence[str]) -> str:
    """Werkzeugliste zu **einem** Argument verbinden.

    Warum komma-verbunden und nicht als Einzelargumente: ``--tools``,
    ``--allowedTools`` und ``--disallowedTools`` sind in der Claude-CLI
    **variadisch** (``<tools...>``, verifiziert gegen ``claude --help``, 2.1.220).
    Als Einzelargumente uebergeben, verschluckt so ein Flag jedes nachfolgende
    Argument, das nicht mit ``--`` beginnt — auch einen positionalen Prompt. Ein
    einziges komma-verbundenes Argument schliesst diese Falle strukturell.

    Die CLI erlaubt beide Formen ausdruecklich ("Comma or space-separated list").
    Der Bestand ist an dieser Stelle uneinheitlich: ``llmauto`` verbindet mit
    Komma (``runner.py:46``), ``swarm-ai`` uebergibt Einzelargumente
    (``runner.py:86``), das Dungeon-Skript beides nebeneinander (Z. 296-297).
    COMAS entscheidet sich fuer die Komma-Form.
    """
    return ",".join(tools)
