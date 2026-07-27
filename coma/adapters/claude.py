"""Adapter fuer die Claude-Code-CLI — der vollstaendige, verifizierte Adapter.

Dies ist die **Vereinigungsmenge** der drei Spawn-Stellen, die vor COMA
unabhaengig voneinander ``claude``-Aufrufe zusammenbauten:

===============================================================  ==========================
Herkunft                                                          Beitrag
===============================================================  ==========================
``llmauto/core/runner.py:17-51``                                  Der Keim: Wrapper-Klasse,
                                                                  ``--fallback-model``,
                                                                  ``--continue``,
                                                                  ``--allowedTools``,
                                                                  konfigurierbarer
                                                                  Permission-Mode
``swarm-ai/tools/runner.py:16-99``                                ``--max-budget-usd``,
                                                                  ``--tools``,
                                                                  ``--disallowedTools mcp__*``,
                                                                  ``--no-session-persistence``,
                                                                  Parametervalidierung
``swarm-ai/experiments/dungeon/…_live.py:283-300``                ``--output-format
                                                                  stream-json``,
                                                                  ``--verbose``,
                                                                  ``--safe-mode``,
                                                                  ``CLAUDECODE``-Bereinigung
``_control-center/START-LOCAL-AGENT.bat:72``                      Standardkonfiguration
                                                                  (Modell ``opus``,
                                                                  Zeiger-Prompt)
===============================================================  ==========================

Alle Flags sind gegen ``claude --help`` (Claude Code 2.1.220, 2026-07-26)
geprueft; keine davon ist geraten.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from .base import AdapterError, CliAdapter, join_tools, normalize_tool_list


class _Sentinel:
    """Ein benannter Platzhalter — unterscheidbar von ``None`` und ``[]``."""

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        self._name = name

    def __repr__(self) -> str:
        return self._name


#: Das Flag entfaellt vollstaendig — keine Einschraenkung durch diese Liste.
NO_RESTRICTION = _Sentinel("NO_RESTRICTION")
#: ``available_tools`` spiegelt ``allowed_tools`` (Verhalten aus swarm-ai).
MIRROR = _Sentinel("MIRROR")

#: Werkzeugprofil aus ``llmauto/core/runner.py:23`` — gepaart mit ``dontAsk``.
DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = ("Read", "Edit", "Write", "Bash", "Glob", "Grep")
#: Werkzeugprofil aus ``swarm-ai/tools/runner.py:31`` — Schreib-/Shell-Zugriff nur auf Ansage.
READ_ONLY_TOOLS: tuple[str, ...] = ("Read", "Glob", "Grep")

#: Auswahl aus ``claude --help`` (2.1.220).
KNOWN_PERMISSION_MODES: tuple[str, ...] = (
    "acceptEdits",
    "auto",
    "bypassPermissions",
    "manual",
    "dontAsk",
    "plan",
)
KNOWN_OUTPUT_FORMATS: tuple[str, ...] = ("text", "json", "stream-json")

#: Der Zeiger-Prompt der Startschale, zeichengenau (``START-LOCAL-AGENT.bat:72``).
POINTER_PROMPT = "Lies die Datei {job_file} und arbeite sie vollstaendig ab."


def _check_budget(value: Any) -> float:
    """``--max-budget-usd`` pruefen (aus ``swarm-ai/tools/runner.py:24-26,96-97``)."""
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise AdapterError("max_budget_usd muss endlich und groesser als null sein")
    return number


class ClaudeAdapter(CliAdapter):
    """Baut ``claude``-Kommandos. Startet nichts.

    Der **Permission-Mode bleibt Parameter** und wird nirgends fest verdrahtet.
    ``dontAsk`` und ``bypassPermissions`` sind verschiedene Sicherheitsprofile:

    * ``dontAsk`` fragt nie, sondern **verweigert**. Zusammen mit einer expliziten
      Werkzeugliste kann ein Agent damit strukturell nicht haengenbleiben. Das ist
      fuer unbeaufsichtigte Laeufe die bessere Wahl und deshalb der Standard.
    * ``bypassPermissions`` kann in Sonderfaellen weiterhin nachfragen — in einer
      Remote-Control-Session heisst das: der Agent steht still, bis jemand klickt.

    Siehe ``KONZEPT.md`` Lektion 4.

    **Empirisch geprueft am 2026-07-26 (CLI 2.1.220):** ``dontAsk`` hat einen
    ``Write`` auf einen absoluten Pfad **ausserhalb** des Arbeitsverzeichnisses
    *nicht* verweigert (Selbsttest ``coma-selftest-nocwd``, Exit 0). Der Adapter
    setzt deshalb kein ``cwd`` von sich aus — ``subprocess`` erbt das des
    Aufrufers, wie im Bestand. Wer den Arbeitsbereich trotzdem festlegen will,
    uebergibt ``cwd=``.

    **Nicht modelliert: ``--add-dir``.** Das Flag existiert
    (``--add-dir <directories...>``, ebenfalls variadisch) und erweitert den
    Werkzeugzugriff auf zusaetzliche Verzeichnisse. Es ist ueber ``extra_args``
    erreichbar. Bewusst kein eigener Parameter: Ob mehrere Verzeichnisse als
    wiederholtes Flag (``--add-dir A --add-dir B``) oder als Werteliste hinter
    einem Flag zu uebergeben sind, ist **nicht verifiziert**, und Pfade koennen
    Kommas enthalten — die Komma-Verbindung wie bei Werkzeuglisten ist hier also
    kein sicherer Ausweg. Eine geratene Kodierung waere schlimmer als keine.
    """

    name = "claude"
    display_name = "Claude Code"
    executable = "claude"
    verified = True
    notes = (
        "Flags gegen claude --help 2.1.220 geprueft (2026-07-26).",
        "Prompt steht direkt nach -p, VOR allen variadischen Flags.",
        "Werkzeuglisten werden komma-verbunden als EIN Argument uebergeben.",
    )

    def __init__(
        self,
        model: str = "opus",
        *,
        fallback_model: str | None = None,
        permission_mode: str = "dontAsk",
        allowed_tools: Sequence[str] | _Sentinel | None = DEFAULT_ALLOWED_TOOLS,
        available_tools: Sequence[str] | _Sentinel | None = MIRROR,
        disallowed_tools: Sequence[str] = ("mcp__*",),
        allow_mcp: bool = False,
        persist_sessions: bool = False,
        safe_mode: bool = False,
        verbose: bool = False,
        output_format: str | None = None,
        max_budget_usd: float | None = None,
        continue_conversation: bool = False,
        extra_args: Sequence[str] = (),
        strict_permission_modes: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.strict_permission_modes = bool(strict_permission_modes)
        self.model = self._check_model(model)
        self.fallback_model = fallback_model
        self.permission_mode = self._check_permission_mode(permission_mode)
        self.allowed_tools = self._store_tools(allowed_tools, "allowed_tools")
        self.available_tools = self._store_tools(
            available_tools, "available_tools", allow_mirror=True
        )
        self.disallowed_tools = normalize_tool_list(disallowed_tools, "disallowed_tools")
        self.allow_mcp = bool(allow_mcp)
        self.persist_sessions = bool(persist_sessions)
        self.safe_mode = bool(safe_mode)
        self.verbose = bool(verbose)
        self.output_format = self._check_output_format(output_format)
        self.max_budget_usd = None if max_budget_usd is None else _check_budget(max_budget_usd)
        self.continue_conversation = bool(continue_conversation)
        self.extra_args = [str(arg) for arg in extra_args]

    # ------------------------------------------------------------------ Presets

    @classmethod
    def preset(cls, name: str, **overrides: Any) -> "ClaudeAdapter":
        """Benanntes Profil erzeugen. Jedes Profil belegt seine Herkunft.

        * ``unattended`` — der Standard: ``dontAsk`` + explizite Werkzeugliste,
          MCP verweigert, keine Sitzungsspeicherung. Profil aus
          ``llmauto/core/runner.py:18,23`` in Verbindung mit den swarm-ai-Riegeln.
        * ``read_only`` — ``dontAsk`` + ``Read,Glob,Grep``: Schreib- und
          Shell-Zugriff nur auf ausdrueckliche Ansage
          (``swarm-ai/tools/runner.py:30-31``).
        * ``bat_compat`` — die verifizierte Konfiguration der Startschale
          (``START-LOCAL-AGENT.bat:72``): ``bypassPermissions``, keine
          Werkzeugeinschraenkung, MCP erlaubt, Sitzungen werden gespeichert.
          Nur benutzen, wenn genau dieses Verhalten gebraucht wird — in einer
          RC-Session kann ``bypassPermissions`` doch nachfragen.
        """
        profiles: dict[str, dict[str, Any]] = {
            "unattended": {},
            "read_only": {"allowed_tools": READ_ONLY_TOOLS},
            "bat_compat": {
                "permission_mode": "bypassPermissions",
                "allowed_tools": NO_RESTRICTION,
                "available_tools": NO_RESTRICTION,
                "allow_mcp": True,
                "persist_sessions": True,
            },
        }
        if name not in profiles:
            raise AdapterError(
                f"unbekanntes Profil {name!r} — bekannt: {', '.join(sorted(profiles))}"
            )
        return cls(**{**profiles[name], **overrides})

    # ------------------------------------------------------------------ Pruefer

    @staticmethod
    def _check_model(model: Any) -> str:
        if not isinstance(model, str) or not model.strip():
            raise AdapterError("model muss ein nicht-leerer String sein")
        return model

    def _check_permission_mode(self, mode: Any) -> str:
        if not isinstance(mode, str) or not mode.strip():
            raise AdapterError("permission_mode muss ein nicht-leerer String sein")
        if self.strict_permission_modes and mode not in KNOWN_PERMISSION_MODES:
            raise AdapterError(
                f"unbekannter permission_mode {mode!r} — bekannt: "
                f"{', '.join(KNOWN_PERMISSION_MODES)}. "
                "Fuer neuere CLI-Versionen: strict_permission_modes=False."
            )
        return mode

    @staticmethod
    def _check_output_format(value: Any) -> str | None:
        if value is None:
            return None
        if value not in KNOWN_OUTPUT_FORMATS:
            raise AdapterError(
                f"unbekanntes output_format {value!r} — erlaubt: "
                f"{', '.join(KNOWN_OUTPUT_FORMATS)}"
            )
        return value

    @staticmethod
    def _store_tools(
        value: Any, field_name: str, *, allow_mirror: bool = False
    ) -> list[str] | _Sentinel:
        if value is NO_RESTRICTION or value is None:
            return NO_RESTRICTION
        if value is MIRROR:
            if not allow_mirror:
                raise AdapterError(f"MIRROR ist fuer {field_name} nicht zulaessig")
            return MIRROR
        return normalize_tool_list(value, field_name)

    # ----------------------------------------------------------------- Kommando

    def pointer_prompt(self, job_file: Any) -> str:
        """Kurz und zeichenarm — alle Anweisungen stehen in der Auftragsdatei.

        Zeichengenau der Prompt der Startschale (``START-LOCAL-AGENT.bat:72``).
        Der Grund war dort das CMD-Quoting (``KONZEPT.md`` Lektion 1); in Python
        entfaellt dieses Risiko, weil ``subprocess`` die Argumente ohne Shell
        uebergibt. Die Regel bleibt trotzdem: die Rueckgabe soll nicht an der
        stdout-Groesse haengen, und der Prompt bleibt zwischen ``.bat`` und
        Python vergleichbar.
        """
        return POINTER_PROMPT.format(job_file=job_file)

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        """Die Argumentliste bauen.

        **Reihenfolge ist hier Sicherheitseigenschaft, nicht Geschmack:** Der
        Prompt steht direkt nach ``-p`` und damit vor jedem variadischen Flag
        (``--tools``, ``--allowedTools``, ``--disallowedTools`` sind
        ``<tools...>``). Stuende er am Ende, verschluckte ihn ein vorangehendes
        variadisches Flag als Werkzeugnamen.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError("prompt muss ein nicht-leerer String sein")

        model = self._check_model(overrides.get("model", self.model))
        permission_mode = self._check_permission_mode(
            overrides.get("permission_mode", self.permission_mode)
        )

        allowed_given = "allowed_tools" in overrides
        allowed = self._store_tools(
            overrides["allowed_tools"] if allowed_given else self.allowed_tools,
            "allowed_tools",
        )
        if "available_tools" in overrides:
            available = self._store_tools(
                overrides["available_tools"], "available_tools", allow_mirror=True
            )
        elif allowed_given:
            # Wer die Freigabeliste ueberschreibt, meint auch die Verfuegbarkeit.
            available = MIRROR
        else:
            available = self.available_tools
        if available is MIRROR:
            available = allowed

        disallowed = normalize_tool_list(
            overrides.get("disallowed_tools", self.disallowed_tools), "disallowed_tools"
        )
        allow_mcp = bool(overrides.get("allow_mcp", self.allow_mcp))
        persist = bool(overrides.get("persist_sessions", self.persist_sessions))
        safe_mode = bool(overrides.get("safe_mode", self.safe_mode))
        verbose = bool(overrides.get("verbose", self.verbose))
        output_format = self._check_output_format(
            overrides.get("output_format", self.output_format)
        )
        fallback = overrides.get("fallback_model", self.fallback_model)
        budget = overrides.get("max_budget_usd", self.max_budget_usd)
        continue_conv = bool(
            overrides.get("continue_conversation", self.continue_conversation)
        )
        extra = [str(arg) for arg in overrides.get("extra_args", self.extra_args)]

        cmd = [self.executable, "-p", prompt]
        if continue_conv:
            cmd.append("--continue")
        cmd.extend(["--model", model])
        cmd.extend(["--permission-mode", permission_mode])

        # --tools begrenzt, welche Built-ins ueberhaupt existieren;
        # --allowedTools gibt sie vorab frei. Zwei verschiedene Dinge —
        # der Kommentar in swarm-ai/tools/runner.py:83 sagt es explizit.
        if available is not NO_RESTRICTION:
            cmd.extend(["--tools", join_tools(available)])
        if allowed is not NO_RESTRICTION and allowed:
            cmd.extend(["--allowedTools", join_tools(allowed)])
        # MCP laesst sich ueber --tools nicht abschalten: dort stehen nur
        # Built-ins. Deshalb eine eigene Deny-Regel.
        if not allow_mcp and disallowed:
            cmd.extend(["--disallowedTools", join_tools(disallowed)])

        if fallback:
            cmd.extend(["--fallback-model", str(fallback)])
        if budget is not None:
            cmd.extend(["--max-budget-usd", str(_check_budget(budget))])
        if output_format is not None:
            cmd.extend(["--output-format", output_format])
            if output_format == "stream-json":
                # Erzwungen, nicht optional: die CLI lehnt stream-json unter -p
                # ohne --verbose ab. Im Dungeon-Skript stehen beide Flags
                # deshalb nebeneinander (Z. 291 und 298) — wer nur eines
                # setzt, baut eine Option, die zur Laufzeit stirbt.
                verbose = True
        if not persist:
            cmd.append("--no-session-persistence")
        if safe_mode:
            cmd.append("--safe-mode")
        if verbose:
            cmd.append("--verbose")
        cmd.extend(extra)
        return cmd
