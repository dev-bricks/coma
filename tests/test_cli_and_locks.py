# -*- coding: utf-8 -*-
"""CLI und Lock-Schnittstelle.

Bei der CLI wird vor allem eines geprueft: ``--dry-run`` und ``cmd`` starten
nichts. Das ist der Befehl, mit dem man vor einem teuren Lauf nachsieht.

Bei den Locks wird geprueft, dass die Schnittstelle **passt** — nicht, dass sie
sperrt. COMAS sperrt nichts.
"""
import json

import pytest

from comas import LockBackend, LockDenied, NullLock, claimed
from comas.cli import main
from comas.manifest import MANIFEST_FILENAME


def run_cli(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr().out


class TestDryRun:
    def test_run_dry_starts_nothing(self, board, job, monkeypatch, capsys):
        def forbidden(*args, **kwargs):  # pragma: no cover - darf nicht passieren
            raise AssertionError("--dry-run darf nichts starten")

        monkeypatch.setattr("comas.spawn.subprocess.run", forbidden)
        monkeypatch.setattr("comas.spawn.subprocess.Popen", forbidden)
        code, out = run_cli(
            ["--root", str(board.root), "run", "testjob", "--dry-run"], capsys
        )
        assert code == 0
        assert "claude" in out
        assert not job.status_file.exists()

    def test_dry_run_as_json_lists_the_argv(self, board, job, capsys):
        code, out = run_cli(
            ["--root", str(board.root), "--json", "run", "testjob", "--dry-run"], capsys
        )
        payload = json.loads(out)
        assert code == 0
        assert payload["argv"][0] == "claude"
        assert payload["verified"] is True

    def test_cmd_shows_the_union_of_flags(self, capsys):
        code, out = run_cli(
            [
                "--json",
                "cmd",
                "Sag Hallo",
                "--model",
                "sonnet",
                "--fallback-model",
                "haiku",
                "--permission-mode",
                "dontAsk",
                "--allowed-tools",
                "Read,Write",
                "--tools",
                "Read,Write,Bash",
                "--max-budget-usd",
                "1.5",
                "--output-format",
                "stream-json",
                "--safe-mode",
            ],
            capsys,
        )
        argv = json.loads(out)["argv"]
        assert code == 0
        for flag in (
            "--model",
            "--fallback-model",
            "--permission-mode",
            "--allowedTools",
            "--tools",
            "--disallowedTools",
            "--max-budget-usd",
            "--output-format",
            "--safe-mode",
            "--verbose",
            "--no-session-persistence",
        ):
            assert flag in argv, f"{flag} fehlt"

    def test_dash_means_omit_the_flag(self, capsys):
        code, out = run_cli(
            ["--json", "cmd", "Hallo", "--allowed-tools", "-", "--tools", "-"], capsys
        )
        argv = json.loads(out)["argv"]
        assert "--allowedTools" not in argv and "--tools" not in argv

    def test_empty_tools_disables_all_builtins(self, capsys):
        code, out = run_cli(
            ["--json", "cmd", "Hallo", "--allowed-tools", "", "--tools", ""], capsys
        )
        argv = json.loads(out)["argv"]
        assert argv[argv.index("--tools") + 1] == ""

    def test_preset_bat_compat(self, capsys):
        code, out = run_cli(["--json", "cmd", "Hallo", "--preset", "bat_compat"], capsys)
        argv = json.loads(out)["argv"]
        assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
        assert "--tools" not in argv

    def test_preset_can_be_overridden_on_the_command_line(self, capsys):
        code, out = run_cli(
            ["--json", "cmd", "Hallo", "--preset", "read_only", "--model", "haiku"],
            capsys,
        )
        argv = json.loads(out)["argv"]
        assert argv[argv.index("--model") + 1] == "haiku"
        assert argv[argv.index("--allowedTools") + 1] == "Read,Glob,Grep"

    def test_dry_run_works_for_unverified_adapters_too(self, board, job, capsys):
        # Bauen darf man immer; erst der echte Start braucht --allow-unverified.
        code, out = run_cli(
            [
                "--root",
                str(board.root),
                "--json",
                "run",
                "testjob",
                "--adapter",
                "agy",
                "--dry-run",
            ],
            capsys,
        )
        payload = json.loads(out)
        assert code == 0
        assert payload["adapter"] == "agy"
        assert payload["verified"] is False


class TestReadCommands:
    def test_submit_status_list_result_log(self, board, tmp_path, capsys):
        source = tmp_path / "auftrag.md"
        source.write_text("# Auftrag\n", encoding="utf-8")
        code, out = run_cli(
            ["--root", str(board.root), "submit", "neu", "--file", str(source)], capsys
        )
        assert code == 0 and "abgelegt" in out

        code, out = run_cli(["--root", str(board.root), "list"], capsys)
        assert code == 0 and "neu" in out

        # Noch kein Status -> Exitcode 1, aber keine Ausnahme.
        code, out = run_cli(["--root", str(board.root), "status", "neu"], capsys)
        assert code == 1 and "kein Status" in out

        code, out = run_cli(["--root", str(board.root), "result", "neu"], capsys)
        assert code == 1 and "keine Ergebnisdatei" in out

        code, out = run_cli(["--root", str(board.root), "log", "neu"], capsys)
        assert code == 1 and "kein Log" in out

    def test_submit_refuses_to_overwrite(self, board, tmp_path, capsys):
        source = tmp_path / "a.md"
        source.write_text("x", encoding="utf-8")
        run_cli(["--root", str(board.root), "submit", "neu", "--file", str(source)], capsys)
        code, _ = run_cli(
            ["--root", str(board.root), "submit", "neu", "--file", str(source)], capsys
        )
        assert code == 2

    def test_send_and_inbox(self, board, job, capsys):
        code, out = run_cli(
            ["--root", str(board.root), "send", "testjob", "bitte warten"], capsys
        )
        assert code == 0 and "gesendet" in out
        assert "bitte warten" in job.to_agent_file.read_text(encoding="utf-8")

        code, out = run_cli(
            ["--root", str(board.root), "send", "testjob", '{"kind":"hint","n":2}'], capsys
        )
        assert code == 0
        records = [
            json.loads(line)
            for line in job.to_agent_file.read_text(encoding="utf-8").splitlines()
        ]
        assert records[1]["kind"] == "hint"

        code, out = run_cli(["--root", str(board.root), "inbox", "testjob"], capsys)
        assert code == 0 and "keine Meldungen" in out

    def test_list_on_empty_board(self, board, capsys):
        code, out = run_cli(["--root", str(board.root), "list"], capsys)
        assert code == 0 and "keine Jobs" in out

    def test_adapters_marks_the_skeletons(self, capsys):
        code, out = run_cli(["adapters"], capsys)
        assert code == 0
        assert "claude" in out and "geprueft" in out
        assert out.count("GERUEST") >= 3

    def test_unknown_job_id_is_a_clean_error(self, board, capsys):
        code, _ = run_cli(["--root", str(board.root), "status", "../flucht"], capsys)
        assert code == 2


class TestCheckCommand:
    def test_exit_code_one_on_drift(self, tmp_path, capsys):
        import shutil

        source = tmp_path / "quelle" / "comas"
        (source / "adapters").mkdir(parents=True)
        (source / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
        (source / "spawn.py").write_text("a = 1\n", encoding="utf-8")
        consumer = tmp_path / "konsument"
        consumer.mkdir()
        shutil.copytree(source, consumer / "vendor" / "comas")

        code, out = run_cli(
            [
                "vendor",
                str(consumer / MANIFEST_FILENAME),
                "--path",
                "vendor/comas",
                "--source",
                str(source),
            ],
            capsys,
        )
        assert code == 0 and "Manifest geschrieben" in out

        code, out = run_cli(["check", str(consumer / MANIFEST_FILENAME)], capsys)
        assert code == 0 and "Kein Drift" in out

        # Kopie anfassen -> Exitcode 1. Genau das kann ein Bericht nicht.
        (consumer / "vendor" / "comas" / "spawn.py").write_text("a = 2\n", encoding="utf-8")
        code, out = run_cli(["check", str(consumer / MANIFEST_FILENAME)], capsys)
        assert code == 1
        assert "MODIFIED" in out

    def test_check_without_argument_searches_the_root(self, tmp_path, capsys):
        code, out = run_cli(["--root", str(tmp_path), "check"], capsys)
        assert code == 0 and MANIFEST_FILENAME in out

    def test_broken_manifest_gives_exit_code_two(self, tmp_path, capsys):
        path = tmp_path / MANIFEST_FILENAME
        path.write_text("{kaputt", encoding="utf-8")
        code, _ = run_cli(["check", str(path)], capsys)
        assert code == 2


class TestLockInterface:
    def test_nulllock_satisfies_the_protocol(self):
        assert isinstance(NullLock(), LockBackend)

    def test_nulllock_grants_everything_and_remembers_nothing(self):
        lock = NullLock()
        assert lock.claim("x") is True
        assert lock.release("x") is True
        assert lock.status()["held"] == []

    def test_claimed_releases_on_the_way_out(self):
        calls = []

        class Spy:
            def claim(self, resource, *, kind="file", ttl_seconds=86400):
                calls.append(("claim", resource, kind, ttl_seconds))
                return True

            def release(self, resource, *, kind="file"):
                calls.append(("release", resource, kind))
                return True

            def status(self, resource=None):
                return {}

        with claimed(Spy(), "projekt", kind="project", ttl_seconds=60) as granted:
            assert granted is True
        assert calls == [
            ("claim", "projekt", "project", 60),
            ("release", "projekt", "project"),
        ]

    def test_claimed_releases_even_on_exception(self):
        released = []

        class Spy:
            def claim(self, resource, *, kind="file", ttl_seconds=86400):
                return True

            def release(self, resource, *, kind="file"):
                released.append(resource)
                return True

            def status(self, resource=None):
                return {}

        with pytest.raises(RuntimeError, match="mitten drin"):
            with claimed(Spy(), "x"):
                raise RuntimeError("mitten drin")
        assert released == ["x"]

    def test_denied_claim_raises_by_default(self):
        class Never:
            def claim(self, resource, *, kind="file", ttl_seconds=86400):
                return False

            def release(self, resource, *, kind="file"):  # pragma: no cover
                raise AssertionError("nichts zu geben, nichts zu nehmen")

            def status(self, resource=None):
                return {}

        with pytest.raises(LockDenied, match="nicht gewaehrt"):
            with claimed(Never(), "x"):
                pass

    def test_denied_claim_can_be_tolerated(self):
        class Never:
            def claim(self, resource, *, kind="file", ttl_seconds=86400):
                return False

            def release(self, resource, *, kind="file"):  # pragma: no cover
                raise AssertionError("nichts freizugeben")

            def status(self, resource=None):
                return {}

        with claimed(Never(), "x", required=False) as granted:
            assert granted is False

    def test_comas_itself_never_locks(self):
        """Keine Datei des Moduls darf ein Lock-Modul importieren."""
        import comas
        from pathlib import Path

        forbidden = ("lock_master", "lock-master", "team_lock", "roshambo")
        for path in Path(comas.__file__).parent.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            for name in forbidden:
                assert f"import {name}" not in text, f"{path.name} importiert {name}"
