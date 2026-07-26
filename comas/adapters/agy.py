"""Adaptergeruest fuer Gemini/Antigravity (``agy``) — **nicht live geprueft.**

``verified = False``: :class:`comas.spawn.Spawner` startet diesen Adapter nur mit
ausdruecklichem ``allow_unverified=True``.

Quelle der Aufrufkonvention: ``~/CLAUDE.md``, Abschnitt „Gemini (antigravity)".
Dort empirisch belegt, hier nur abgeleitet — vor scharfer Nutzung dort nachlesen.

Die harten Punkte:

1. **``agy -p`` liefert Exit 0, aber keinen stdout.** Der TUI-Text-Drip-Renderer
   schreibt in den Terminal-Buffer, nicht nach stdout (bekannte Bugs:
   antigravity-cli#76, gemini-cli#27466). Die Rueckgabe **muss** ueber eine Datei
   laufen — deshalb ist ``result_file`` im Zeiger-Prompt Pflicht, nicht Komfort.
   Fuer COMAS ist das kein Sonderfall: das Protokoll gibt ohnehin Dateien zurueck.
2. **Berechtigung und Workspace sind zwei verschiedene Dinge.**
   ``--dangerously-skip-permissions`` hebt nur die Tool-Freigabe auf und
   erweitert den Workspace **nicht**. Wo geschrieben werden darf, legt
   ``--add-dir <dir>`` fest. Es gibt keinen „ganzes-Dateisystem"-Schalter. Fehlt
   ``--add-dir``, landen Schreibvorgaenge im Default-Workspace und wirken
   halluziniert: Erfolg gemeldet, Datei nicht auffindbar.
3. **Es gibt nur ``agy.exe``, keine ``agy.cmd``.** Der PATH-Eintrag greift erst
   nach einem Terminal-Neustart; aus Subprozessen deshalb den absoluten Pfad.
4. **Nicht ueber ``companion-for-agy`` fuer lange oder CJK-Antworten.** Der
   ANSI-Rueckgabeweg verstuemmelt CJK zu Ersatzzeichen (U+FFFD).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .base import AdapterError, CliAdapter

#: Absoluter Pfad aus ``~/CLAUDE.md`` — es gibt nur die ``.exe``.
DEFAULT_EXECUTABLE = str(
    Path(os.environ.get("LOCALAPPDATA", r"C:\Users\lukas\AppData\Local"))
    / "agy"
    / "bin"
    / "agy.exe"
)
#: Bevorzugte Modelle laut ``~/CLAUDE.md``.
PREFERRED_MODELS: tuple[str, ...] = ("gemini-3.5-flash", "gemini-3.5-pro")

POINTER_PROMPT = (
    "Read the file {job_file} and follow it completely. "
    "Write your result to the file {result_file} as UTF-8."
)


class AgyAdapter(CliAdapter):
    """Baut ``agy.exe``-Kommandos. Geruest, nicht live geprueft."""

    name = "agy"
    display_name = "Gemini / Antigravity (agy)"
    executable = DEFAULT_EXECUTABLE
    verified = False
    notes = (
        "GERUEST: Kommandobau getestet, Aufrufweg nicht live geprueft.",
        "agy -p gibt KEINEN stdout aus — Rueckgabe zwingend ueber Datei.",
        "--add-dir bestimmt den Workspace; die Permission-Flag tut das NICHT.",
        "Nur agy.exe, keine agy.cmd; aus Subprozessen absoluten Pfad nutzen.",
        "companion-for-agy verstuemmelt CJK — nur fuer kurze ASCII-Antworten.",
    )

    def __init__(
        self,
        model: str = "gemini-3.5-pro",
        *,
        add_dirs: Sequence[str | os.PathLike[str]] = (),
        skip_permissions: bool = True,
        extra_args: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not isinstance(model, str) or not model.strip():
            raise AdapterError("model muss ein nicht-leerer String sein")
        self.model = model
        self.add_dirs = [str(path) for path in add_dirs]
        self.skip_permissions = bool(skip_permissions)
        self.extra_args = [str(arg) for arg in extra_args]

    def pointer_prompt(self, job_file: Any, result_file: Any = None) -> str:
        """Zeiger-Prompt auf Englisch mit Pflicht-Zielpfad.

        Englisch, weil das die dokumentierte Form ist, mit der die Datei-Rueckgabe
        verifiziert wurde. Der Zielpfad ist Pflicht (Punkt 1 im Modul-Docstring):
        ohne Datei gibt es kein Ergebnis, denn stdout bleibt leer.
        """
        if result_file is None:
            raise AdapterError(
                "agy gibt keinen stdout aus — result_file ist Pflicht, "
                "sonst ist das Ergebnis nicht abholbar"
            )
        return POINTER_PROMPT.format(job_file=job_file, result_file=result_file)

    def build_cmd(self, prompt: str, **overrides: Any) -> list[str]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise AdapterError("prompt muss ein nicht-leerer String sein")
        model = overrides.get("model", self.model)
        add_dirs = [str(p) for p in overrides.get("add_dirs", self.add_dirs)]
        skip = bool(overrides.get("skip_permissions", self.skip_permissions))

        cmd = [self.executable]
        if skip:
            cmd.append("--dangerously-skip-permissions")
        for directory in add_dirs:
            # Ein --add-dir je Verzeichnis: das ist der Workspace-Scope.
            cmd.extend(["--add-dir", directory])
        cmd.extend(["--model", str(model)])
        cmd.extend(str(arg) for arg in overrides.get("extra_args", self.extra_args))
        cmd.extend(["-p", prompt])
        return cmd
