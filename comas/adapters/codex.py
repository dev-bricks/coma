"""Adaptergeruest fuer Codex (GPT) — **nicht live geprueft.**

``verified = False``: :class:`comas.spawn.Spawner` startet diesen Adapter nur,
wenn der Aufrufer ausdruecklich ``allow_unverified=True`` setzt. Der Kommandobau
ist vollstaendig und getestet, der echte Aufrufweg ist es nicht.

Quelle der Aufrufkonvention: ``~/CLAUDE.md``, Abschnitt „Codex CLI (GPT) —
Nutzung aus Claude Code". Nichts davon ist geraten; alles ist dort empirisch
belegt. Vor der ersten scharfen Nutzung diesen Abschnitt erneut lesen — er ist
die gepflegte Quelle, dieser Docstring nur die Ableitung.

Die harten Punkte:

1. **Nicht ``codex exec`` per Pipe.** Haengt im PowerShell-Kontext
   (stdin-Handling-Bug). Stattdessen das Companion-Skript.
2. **Der Companion-Pfad ist versionslos zu halten.** ``marketplaces/…`` ueberlebt
   Plugin-Updates; der Pfad unter ``cache/openai-codex/codex/<version>/`` wandert
   bei jedem Update und stirbt mit ``MODULE_NOT_FOUND``.
3. **Ohne ``--write`` laeuft der Turn read-only** (``sandbox: "read-only"``) und
   kann nur ueber stdout antworten — bei langen Antworten wird das abgeschnitten.
   Fuer Dateirueckgabe ``--write`` setzen.
4. **Die beschreibbare Wurzel ist der git-Repo-Root von cwd**, sonst cwd selbst.
   Also aus dem Zielprojekt heraus aufrufen oder ``-C`` setzen; der Zielordner
   muss **vorher existieren**; im Prompt den **relativen** Zielpfad nennen.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .base import AdapterError, CliAdapter

#: Versionsloser Companion-Pfad (siehe Punkt 2 im Modul-Docstring).
COMPANION_RELATIVE = (
    ".claude/plugins/marketplaces/openai-codex/plugins/codex/scripts/codex-companion.mjs"
)
KNOWN_EFFORTS: tuple[str, ...] = ("none", "low", "medium", "high", "xhigh")

POINTER_PROMPT = (
    "Lies die Datei {job_file} und arbeite sie vollstaendig ab. "
    "Schreibe dein Ergebnis nach {result_file}."
)


def default_companion_path(home: Path | None = None) -> Path:
    """Den Companion im Home des Nutzers verorten (ohne zu pruefen, ob er da ist)."""
    return (home or Path.home()) / COMPANION_RELATIVE


class CodexAdapter(CliAdapter):
    """Baut ``node <companion> task …``-Kommandos. Geruest, nicht live geprueft."""

    name = "codex"
    display_name = "Codex (GPT) via codex-companion.mjs"
    executable = "node"
    verified = False
    notes = (
        "GERUEST: Kommandobau getestet, Aufrufweg nicht live geprueft.",
        "codex exec per Pipe haengt in PowerShell — nur der Companion.",
        "Companion-Pfad versionslos halten (marketplaces/, nicht cache/<version>/).",
        "Ohne --write laeuft der Turn read-only und kann keine Datei schreiben.",
        "Beschreibbare Wurzel = git-Repo-Root von cwd; Zielordner muss existieren.",
    )

    def __init__(
        self,
        *,
        companion: str | Path | None = None,
        effort: str | None = None,
        write: bool = False,
        model: str | None = None,
        extra_args: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.companion = Path(companion) if companion else default_companion_path()
        self.effort = self._check_effort(effort)
        self.write = bool(write)
        self.model = model
        self.extra_args = [str(arg) for arg in extra_args]

    @staticmethod
    def _check_effort(value: Any) -> str | None:
        if value is None:
            return None
        if value not in KNOWN_EFFORTS:
            raise AdapterError(
                f"unbekanntes effort {value!r} — erlaubt: {', '.join(KNOWN_EFFORTS)}"
            )
        return value

    def pointer_prompt(self, job_file: Any, result_file: Any = None) -> str:
        """Zeiger-Prompt mit ausdruecklichem Ergebnispfad.

        Codex braucht den Zielpfad im Prompt, weil die Sandbox-Wurzel aus cwd
        abgeleitet wird und ein **relativer** Pfad erwartet ist.
        """
        return POINTER_PROMPT.format(
            job_file=job_file, result_file=result_file or "<Ergebnisdatei>"
        )

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError("prompt muss ein nicht-leerer String sein")
        companion = Path(overrides.get("companion", self.companion))
        effort = self._check_effort(overrides.get("effort", self.effort))
        write = bool(overrides.get("write", self.write))
        model = overrides.get("model", self.model)
        cwd = overrides.get("cwd", self.cwd)

        cmd = [self.executable, str(companion), "task"]
        if write:
            # Ohne dieses Flag laeuft der Turn read-only und kann keine Datei anlegen.
            cmd.append("--write")
        if effort:
            cmd.extend(["--effort", effort])
        if model:
            cmd.extend(["--model", str(model)])
        if cwd:
            # -C setzt cwd des Turns; die beschreibbare Wurzel folgt daraus.
            cmd.extend(["-C", str(cwd)])
        cmd.extend(str(arg) for arg in overrides.get("extra_args", self.extra_args))
        cmd.append(prompt)
        return cmd
