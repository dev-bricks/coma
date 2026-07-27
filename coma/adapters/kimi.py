"""Adaptergeruest fuer Kimi Code CLI — **nicht live geprueft.**

``verified = False``: :class:`coma.spawn.Spawner` startet diesen Adapter nur mit
ausdruecklichem ``allow_unverified=True``.

Quelle der Aufrufkonvention: ``~/CLAUDE.md``, Abschnitt „Kimi (Kimi Code CLI)"
(dort als „verifiziert 2026-06-17" vermerkt). Hier nur abgeleitet.

Die harten Punkte:

1. **``-p`` laesst sich nicht mit ``-y/--yolo`` oder ``--auto`` kombinieren** —
   die CLI bricht mit „Cannot combine --prompt with --yolo/--auto" ab. ``-p``
   deshalb pur nutzen. Der Adapter erzwingt das, statt es dem Aufrufer zu
   ueberlassen.
2. **Aus dem Zielprojekt heraus aufrufen** (cwd = Workspace). Der
   Default-Permission-Modus darf Dateien schreiben.
3. **Die Binary liegt nicht im PATH.** Befehl ist ``kimi``, die ausfuehrbare
   Datei ``kimi-code.exe`` unter ``…/Programs/kimi-code/``. Der npm-Shim
   ``kimi.CMD`` existiert daneben — den meiden: eine ``.CMD`` wird von Windows
   erneut durch ``cmd.exe`` geparst, und damit gilt wieder die
   Quoting-Lektion aus ``KONZEPT.md`` (Lektion 1), die in Python sonst entfaellt.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .base import AdapterError, CliAdapter

#: NPM-Installation auf Windows: Node direkt aufrufen, nicht den CMD-Shim.
DEFAULT_ENTRYPOINT = (
    Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    / "npm"
    / "node_modules"
    / "@moonshot-ai"
    / "kimi-code"
    / "dist"
    / "main.mjs"
)
KNOWN_OUTPUT_FORMATS: tuple[str, ...] = ("text", "stream-json")

POINTER_PROMPT = (
    "Lies die Datei {job_file} und arbeite sie vollständig ab. "
    "Schreibe das Ergebnis als UTF-8 nach {result_file}."
)


class KimiAdapter(CliAdapter):
    """Baut ``kimi-code.exe -p …``-Kommandos. Geruest, nicht live geprueft."""

    name = "kimi"
    display_name = "Kimi Code CLI"
    executable = "node" if os.name == "nt" else "kimi"
    verified = False
    notes = (
        "GERUEST: Kommandobau getestet, Aufrufweg nicht live geprueft.",
        "-p ist nicht mit -y/--yolo oder --auto kombinierbar.",
        "Aus dem Zielprojekt heraus aufrufen (cwd = Workspace).",
        "Windows: Node-Entrypoint direkt; npm-Shim kimi.CMD wird nicht reparst.",
    )

    def __init__(
        self,
        model: str | None = None,
        *,
        entrypoint: str | Path | None = None,
        output_format: str | None = None,
        session: str | None = None,
        continue_conversation: bool = False,
        extra_args: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.entrypoint = (
            Path(entrypoint)
            if entrypoint is not None
            else (DEFAULT_ENTRYPOINT if os.name == "nt" else None)
        )
        self.model = model
        self.output_format = self._check_output_format(output_format)
        self.session = session
        self.continue_conversation = bool(continue_conversation)
        self.extra_args = [str(arg) for arg in extra_args]

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

    def pointer_prompt(self, job_file: Any, result_file: Any = None) -> str:
        if result_file is None:
            raise AdapterError("Kimi braucht im COMA-Protokoll eine result_file")
        return POINTER_PROMPT.format(job_file=job_file, result_file=result_file)

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError("prompt muss ein nicht-leerer String sein")
        extra = [str(arg) for arg in overrides.get("extra_args", self.extra_args)]
        forbidden = {"-y", "--yolo", "--auto"}
        clash = forbidden.intersection(extra)
        if clash:
            # Punkt 1: die CLI bricht sonst mit einer Fehlermeldung ab.
            raise AdapterError(
                f"-p ist nicht mit {', '.join(sorted(clash))} kombinierbar "
                "(Kimi bricht mit 'Cannot combine --prompt with --yolo/--auto' ab)"
            )

        cmd = [self.executable]
        entrypoint = overrides.get("entrypoint", self.entrypoint)
        if entrypoint is not None:
            cmd.append(str(entrypoint))
        cmd.extend(["-p", prompt])
        model = overrides.get("model", self.model)
        if model:
            cmd.extend(["-m", str(model)])
        output_format = self._check_output_format(
            overrides.get("output_format", self.output_format)
        )
        if output_format:
            cmd.extend(["--output-format", output_format])
        session = overrides.get("session", self.session)
        if session:
            cmd.extend(["-S", str(session)])
        if bool(overrides.get("continue_conversation", self.continue_conversation)):
            cmd.append("-C")
        cmd.extend(extra)
        return cmd
