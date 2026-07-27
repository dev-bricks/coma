"""Adapter für die native, nichtinteraktive Codex-CLI.

Die frühere Fassung nutzte ein Claude-Plugin-Companion und warnte vor
``codex exec``. Das ist für Codex CLI 0.145.0 veraltet: ``codex exec`` ist der
offizielle Automationsweg und unterstützt Arbeitswurzel, Sandbox, Modell,
Reasoning-Effort sowie eine belastbare Ergebnisdatei.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .base import AdapterError, CliAdapter

KNOWN_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max", "ultra")
KNOWN_SANDBOXES: tuple[str, ...] = ("read-only", "workspace-write", "danger-full-access")

POINTER_PROMPT = "Lies die Datei {job_file} und arbeite sie vollständig ab."


def default_codex_entrypoint(home: Path | None = None) -> Path | None:
    """Windows-NPM-Entrypoint ohne CMD-Reparsing; sonst native CLI."""
    if os.name != "nt":
        return None
    user_home = home or Path.home()
    appdata = Path(os.environ.get("APPDATA") or user_home / "AppData" / "Roaming")
    return appdata / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"


class CodexAdapter(CliAdapter):
    """Baut ``codex exec``-Kommandos für unbeaufsichtigte Läufe."""

    name = "codex"
    display_name = "Codex CLI (native exec)"
    executable = "node" if os.name == "nt" else "codex"
    verified = True
    notes = (
        "Native codex exec flags gegen Codex CLI 0.145.0 geprüft (2026-07-27).",
        "Unter Windows direkter Node-Entrypoint statt CMD/PowerShell-Reparsing.",
        "Standard: read-only, ephemere Sitzung, Hook-Trust bleibt aktiv.",
        "Ergebnis wird mit --output-last-message in die COMAS-Ergebnisdatei geschrieben.",
    )

    def __init__(
        self,
        *,
        entrypoint: str | Path | None = None,
        effort: str | None = None,
        write: bool = False,
        sandbox: str | None = None,
        model: str | None = None,
        persist_sessions: bool = False,
        skip_git_repo_check: bool = True,
        extra_args: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.entrypoint = (
            Path(entrypoint) if entrypoint is not None else default_codex_entrypoint()
        )
        self.effort = self._check_effort(effort)
        self.write = bool(write)
        self.sandbox = self._check_sandbox(sandbox)
        self.model = model
        self.persist_sessions = bool(persist_sessions)
        self.skip_git_repo_check = bool(skip_git_repo_check)
        self.extra_args = [str(arg) for arg in extra_args]

    @staticmethod
    def _check_effort(value: Any) -> str | None:
        if value is None:
            return None
        if value not in KNOWN_EFFORTS:
            raise AdapterError(
                f"unbekanntes effort {value!r} — erlaubt: {', '.join(KNOWN_EFFORTS)}"
            )
        return str(value)

    @staticmethod
    def _check_sandbox(value: Any) -> str | None:
        if value is None:
            return None
        if value not in KNOWN_SANDBOXES:
            raise AdapterError(
                f"unbekannte Sandbox {value!r} — erlaubt: {', '.join(KNOWN_SANDBOXES)}"
            )
        return str(value)

    def pointer_prompt(self, job_file: Any, result_file: Any = None) -> str:
        return POINTER_PROMPT.format(job_file=job_file)

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError("prompt muss ein nicht-leerer String sein")

        entrypoint = overrides.get("entrypoint", self.entrypoint)
        effort = self._check_effort(overrides.get("effort", self.effort))
        write = bool(overrides.get("write", self.write))
        sandbox = self._check_sandbox(overrides.get("sandbox", self.sandbox))
        sandbox = sandbox or ("workspace-write" if write else "read-only")
        model = overrides.get("model", self.model)
        cwd = overrides.get("cwd", self.cwd)
        result_file = overrides.get("result_file")
        persist = bool(overrides.get("persist_sessions", self.persist_sessions))
        skip_repo = bool(
            overrides.get("skip_git_repo_check", self.skip_git_repo_check)
        )

        cmd = [self.executable]
        if entrypoint is not None:
            cmd.append(str(entrypoint))
        cmd.extend(["exec", "--sandbox", sandbox])
        if cwd:
            cmd.extend(["-C", str(cwd)])
        if skip_repo:
            cmd.append("--skip-git-repo-check")
        if not persist:
            cmd.append("--ephemeral")
        if model:
            cmd.extend(["--model", str(model)])
        if effort:
            cmd.extend(["--config", f'model_reasoning_effort="{effort}"'])
        if result_file:
            cmd.extend(["--output-last-message", str(result_file)])
        cmd.extend(str(arg) for arg in overrides.get("extra_args", self.extra_args))
        cmd.append(prompt)
        return cmd
