# -*- coding: utf-8 -*-
"""Spawner: Prozessstart, Timeout, Fehlerbehandlung, Logdatei — alles mit Mocks."""
import subprocess

import pytest

from coma import ClaudeAdapter, SpawnError, Spawner
from coma.spawn import MAX_PARALLEL_ITEMS, ProcessHandle, wait_all


@pytest.fixture
def spawner():
    return Spawner(ClaudeAdapter(timeout=30))


class TestRun:
    def test_success(self, spawner, monkeypatch, fake_run):
        runner = fake_run(returncode=0, stdout="Hallo Welt")
        monkeypatch.setattr("coma.spawn.subprocess.run", runner)
        result = spawner.run("Test")
        assert result["success"] is True
        assert result["output"] == "Hallo Welt"
        assert result["returncode"] == 0
        assert result["duration_s"] >= 0
        assert result["model"] == "opus"
        assert result["adapter"] == "claude"
        assert result["argv"][0] == "claude"
        assert result["timed_out"] is False

    def test_failure(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(returncode=1, stderr="Fehler")
        )
        result = spawner.run("Test")
        assert result["success"] is False
        assert result["returncode"] == 1
        assert "Fehler" in result["stderr"]

    def test_timeout_keeps_the_legacy_exit_code_and_message(
        self, spawner, monkeypatch, fake_run
    ):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run",
            fake_run(raises=subprocess.TimeoutExpired(cmd="claude", timeout=30)),
        )
        result = spawner.run("Test")
        assert result["returncode"] == -1
        assert result["timed_out"] is True
        assert "TIMEOUT nach 30s" in result["stderr"]

    def test_missing_cli_reports_minus_two(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(raises=FileNotFoundError("weg"))
        )
        result = spawner.run("Test")
        assert result["returncode"] == -2
        assert "claude" in result["stderr"]

    def test_other_os_error_reports_minus_three(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(raises=OSError("kaputt"))
        )
        result = spawner.run("Test")
        assert result["returncode"] == -3
        assert "kaputt" in result["stderr"]

    def test_environment_and_argv_reach_subprocess(self, spawner, monkeypatch, fake_run):
        runner = fake_run(returncode=0)
        monkeypatch.setattr("coma.spawn.subprocess.run", runner)
        spawner.run("Test", model="sonnet")
        call = runner.calls[0]
        assert call["cmd"][call["cmd"].index("--model") + 1] == "sonnet"
        assert call["kwargs"]["env"]["PYTHONIOENCODING"] == "utf-8"
        assert call["kwargs"]["timeout"] == 30


class TestLogFile:
    """``> log 2>&1`` in Python — KONZEPT.md Lektion 3."""

    def test_stdout_and_stderr_go_into_the_log(
        self, spawner, tmp_path, monkeypatch, fake_run
    ):
        runner = fake_run(returncode=0, log_text="Zeile eins\nZeile zwei\n")
        monkeypatch.setattr("coma.spawn.subprocess.run", runner)
        log = tmp_path / "unter" / "coma.job.console.log"
        result = spawner.run("Test", log_file=log)
        assert log.is_file()
        assert "Zeile zwei" in log.read_text(encoding="utf-8")
        # Der Aufrufer bekommt trotzdem etwas in die Hand.
        assert "Zeile eins" in result["output"]
        assert result["log_file"] == str(log)
        assert runner.calls[0]["kwargs"]["stderr"] is subprocess.STDOUT

    def test_parent_directory_is_created(self, spawner, tmp_path, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        log = tmp_path / "a" / "b" / "c.log"
        spawner.run("Test", log_file=log)
        assert log.parent.is_dir()

    def test_log_survives_a_timeout(self, spawner, tmp_path, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run",
            fake_run(raises=subprocess.TimeoutExpired(cmd="claude", timeout=1)),
        )
        log = tmp_path / "c.log"
        result = spawner.run("Test", log_file=log)
        assert result["returncode"] == -1
        assert result["log_file"] == str(log)

    def test_tail_limit_is_honoured(self, tmp_path, monkeypatch, fake_run):
        spawner = Spawner(ClaudeAdapter(), log_tail_bytes=10)
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(returncode=0, log_text="x" * 5000)
        )
        result = spawner.run("Test", log_file=tmp_path / "c.log")
        assert len(result["output"]) <= 10


class TestStartAndPoll:
    def test_poll_returns_none_while_running(
        self, spawner, tmp_path, monkeypatch, fake_popen
    ):
        popen = None

        def factory(cmd, **kwargs):
            nonlocal popen
            popen = fake_popen(cmd, **kwargs).program(None, None, 0)
            return popen

        monkeypatch.setattr("coma.spawn.subprocess.Popen", factory)
        handle = spawner.start("Test", log_file=tmp_path / "c.log")
        assert isinstance(handle, ProcessHandle)
        assert handle.pid == 4242
        assert handle.poll() is None
        assert handle.poll() is None
        result = handle.poll()
        assert result is not None and result["returncode"] == 0
        # Zweiter Aufruf liefert denselben Wert, kein neues Ergebnis.
        assert handle.poll() is result

    def test_wait_returns_the_result(self, spawner, tmp_path, monkeypatch, fake_popen):
        monkeypatch.setattr(
            "coma.spawn.subprocess.Popen",
            lambda cmd, **kw: fake_popen(cmd, **kw).program(3),
        )
        handle = spawner.start("Test", log_file=tmp_path / "c.log")
        assert handle.wait()["returncode"] == 3

    def test_start_failure_raises_spawn_error(self, spawner, tmp_path, monkeypatch):
        def boom(cmd, **kwargs):
            raise OSError("kein Prozess")

        monkeypatch.setattr("coma.spawn.subprocess.Popen", boom)
        with pytest.raises(SpawnError, match="kein Prozess"):
            spawner.start("Test", log_file=tmp_path / "c.log")

    def test_wait_all_collects_in_order(self, spawner, tmp_path, monkeypatch, fake_popen):
        codes = iter([7, 8])
        monkeypatch.setattr(
            "coma.spawn.subprocess.Popen",
            lambda cmd, **kw: fake_popen(cmd, **kw).program(next(codes)),
        )
        handles = [
            spawner.start("A", log_file=tmp_path / "a.log"),
            spawner.start("B", log_file=tmp_path / "b.log"),
        ]
        results = wait_all(handles, interval=0.01)
        assert [r["returncode"] for r in results] == [7, 8]


class TestRunMany:
    def test_order_is_preserved(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        results = spawner.run_many(["A", "B", "C"], max_parallel=2)
        assert len(results) == 3
        assert all(result["success"] for result in results)

    def test_dicts_may_carry_overrides(self, spawner, monkeypatch, fake_run):
        runner = fake_run(returncode=0)
        monkeypatch.setattr("coma.spawn.subprocess.run", runner)
        spawner.run_many([{"prompt": "A", "model": "haiku"}, "B"], max_parallel=1)
        models = [
            call["cmd"][call["cmd"].index("--model") + 1] for call in runner.calls
        ]
        assert set(models) == {"haiku", "opus"}

    def test_dict_needs_a_prompt(self, spawner):
        with pytest.raises(ValueError, match="prompt"):
            spawner.run_many([{"model": "haiku"}])

    def test_string_is_not_a_collection_of_prompts(self, spawner):
        with pytest.raises(TypeError, match="kein String"):
            spawner.run_many("abc")

    def test_zero_workers_rejected(self, spawner):
        with pytest.raises(ValueError, match="max_parallel"):
            spawner.run_many(["A"], max_parallel=0)

    def test_upper_bound(self, spawner):
        with pytest.raises(ValueError, match=str(MAX_PARALLEL_ITEMS)):
            spawner.run_many(["A"] * (MAX_PARALLEL_ITEMS + 1))

    def test_worker_exception_becomes_minus_four(self, spawner, monkeypatch):
        def boom(prompt, **overrides):
            raise RuntimeError("Worker tot")

        monkeypatch.setattr(spawner, "run", boom)
        results = spawner.run_many(["A"], max_parallel=1)
        assert results[0]["returncode"] == -4
        assert "Worker tot" in results[0]["stderr"]


class TestPipe:
    def test_returns_text(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(returncode=0, stdout="Antwort")
        )
        assert spawner.pipe("Test") == "Antwort"

    def test_raises_with_the_legacy_message(self, spawner, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(returncode=1, stderr="kaputt")
        )
        with pytest.raises(RuntimeError, match="Claude Fehler"):
            spawner.pipe("Test")
