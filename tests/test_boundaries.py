# -*- coding: utf-8 -*-
"""Die Grenzen des Moduls — als Test, nicht als Absichtserklaerung.

Drei Zusagen aus ``KONZEPT.md`` werden hier nachgeprueft, weil sie sonst beim
naechsten Umbau still verloren gehen:

1. **Extraktion, kein Import.** COMA ist eine Kopie der Logik, keine
   Abhaengigkeit von ``llmauto`` oder ``swarm-ai``. Waere es ein Import, laege
   die Schicht weiterhin in einem Konsumenten.
2. **Keine Abhaengigkeiten.** Kein Netz, kein Konto, kein Cluster — nur
   Standardbibliothek. Das ist der Trennungsgrund gegenueber Roshambo.
3. **Ein Schreiber je Datei.** Nur der Statusschreiber schreibt das Status-JSON.
"""
from pathlib import Path

import coma

PACKAGE = Path(coma.__file__).parent
SOURCES = sorted(PACKAGE.rglob("*.py"))


def text_of(path):
    return path.read_text(encoding="utf-8")


class TestExtractionNotImport:
    def test_no_module_imports_llmauto_or_swarm(self):
        forbidden = ("llmauto", "swarm_ai", "swarm-ai")
        for path in SOURCES:
            body = text_of(path)
            for name in forbidden:
                assert f"import {name}" not in body, f"{path.name} importiert {name}"
                assert f"from {name}" not in body, f"{path.name} importiert aus {name}"

    def test_provenance_is_documented_in_the_code(self):
        """Die Herkunft steht im Code, nicht nur im Ergebnisbericht."""
        claude = text_of(PACKAGE / "adapters" / "claude.py")
        assert "llmauto/core/runner.py" in claude
        assert "swarm-ai/tools/runner.py" in claude
        assert "START-LOCAL-AGENT.bat" in claude
        spawn = text_of(PACKAGE / "spawn.py")
        assert "llmauto/core/runner.py" in spawn


class TestNoDependencies:
    def test_only_standard_library_is_imported(self):
        allowed_third_party: set[str] = set()
        stdlib_ok = {
            "__future__",
            "argparse",
            "contextlib",
            "concurrent",
            "dataclasses",
            "datetime",
            "hashlib",
            "inspect",
            "json",
            "math",
            "os",
            "pathlib",
            "re",
            "shutil",
            "subprocess",
            "sys",
            "time",
            "types",
            "typing",
        }
        import ast

        for path in SOURCES:
            tree = ast.parse(text_of(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relativer Import innerhalb von coma
                        continue
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    assert name in stdlib_ok | allowed_third_party, (
                        f"{path.name} importiert {name!r} — COMA bleibt "
                        "abhaengigkeitsfrei"
                    )

    def test_pyproject_declares_no_dependencies(self):
        pyproject = text_of(PACKAGE.parent / "pyproject.toml")
        assert "dependencies = []" in pyproject


class TestSingleWriterPerFile:
    def test_only_status_module_writes_the_status_json(self):
        """``write_json`` ist der einzige Weg in die Statusdatei."""
        for path in SOURCES:
            if path.name in ("status.py", "manifest.py"):
                continue
            body = text_of(path)
            assert "json.dump(" not in body, (
                f"{path.name} schreibt JSON direkt — Statusdateien laufen ueber "
                "StatusWriter, damit es bei einem Schreiber bleibt"
            )

    def test_channels_only_append(self):
        body = text_of(PACKAGE / "channels.py")
        assert '"a"' in body  # Append-Modus
        assert '"w"' not in body  # kein Ueberschreiben eines Kanals


class TestPublicSurface:
    def test_the_four_verbs_are_reachable(self):
        # spawn, send, poll, result — das Vokabular von COMA.
        assert hasattr(coma, "Spawner")  # spawn
        assert hasattr(coma, "to_agent")  # send
        assert hasattr(coma, "wait_for_finish")  # poll
        assert hasattr(coma, "read_result")  # result

    def test_lock_verbs_are_only_a_protocol(self):
        """claim/release/status gehoeren einem anderen System — hier nur die Form."""
        assert hasattr(coma, "LockBackend")
        assert not hasattr(coma, "claim")
        assert not hasattr(coma, "release")

    def test_everything_in_all_exists(self):
        for name in coma.__all__:
            assert hasattr(coma, name), f"__all__ nennt {name}, das es nicht gibt"

    def test_version_is_readable_without_import(self):
        from coma.manifest import read_version

        assert read_version(PACKAGE) == coma.__version__
