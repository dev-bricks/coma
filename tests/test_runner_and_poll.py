# -*- coding: utf-8 -*-
"""JobRunner und Poll-Hilfen — der Ablauf der Startschale, ohne echten Prozess.

Die Reihenfolge der Schritte ist der eigentliche Pruefgegenstand: Wenn der Status
erst nach dem Lauf geschrieben wuerde, koennte ein Orchestrator nie sehen, dass
etwas laeuft.
"""
import subprocess

import pytest

from coma import (
    ClaudeAdapter,
    JobRunner,
    is_finished,
    is_running,
    job_view,
    overview,
    read_console_log,
    read_result,
    read_status,
    state,
    wait_for_finish,
)


@pytest.fixture
def runner(board):
    return JobRunner(board, ClaudeAdapter(timeout=30))


class TestRun:
    def test_success_path_matches_the_startschale(
        self, runner, board, job, monkeypatch, fake_run
    ):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run", fake_run(returncode=0, log_text="fertig\n")
        )
        job.result_file.parent.mkdir(parents=True, exist_ok=True)
        job.result_file.write_text("Ergebnis\n", encoding="utf-8")

        result = runner.run("testjob")

        assert result["returncode"] == 0
        assert result["status"]["state"] == "done"
        assert result["status"]["exit_code"] == 0
        assert result["result_written"] is True
        # Schritt 7: bei Exitcode 0 wandert der Auftrag nach DONE/.
        assert result["archived"] == str(job.done_file)
        assert job.done_file.is_file()
        assert not job.job_file.exists()
        # Schritt 3: der Kanal zum Agenten liegt bereit.
        assert job.to_agent_file.is_file()
        # Schritt 5: das Log existiert.
        assert job.console_log.is_file()

    def test_failure_leaves_the_job_in_in(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=2))
        result = runner.run("testjob")
        assert result["status"]["state"] == "failed"
        assert result["archived"] is None
        # Damit nichts still verloren geht (.bat:82).
        assert job.job_file.is_file()
        assert not job.done_file.exists()

    def test_status_is_written_before_the_process_starts(
        self, runner, board, job, monkeypatch
    ):
        seen = {}

        def spy(cmd, **kwargs):
            seen["state"] = state(board.paths("testjob"))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr("coma.spawn.subprocess.run", spy)
        runner.run("testjob")
        assert seen["state"] == "running"

    def test_argv_is_recorded_in_the_status(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        result = runner.run("testjob")
        argv = result["status"]["argv"]
        assert argv[0] == "claude"
        assert argv[1] == "-p"
        assert str(job.job_file) in argv[2]
        assert result["status"]["adapter"] == "claude"

    def test_pointer_prompt_points_at_the_job_file(
        self, runner, board, job, monkeypatch, fake_run
    ):
        capture = fake_run(returncode=0)
        monkeypatch.setattr("coma.spawn.subprocess.run", capture)
        runner.run("testjob")
        prompt = capture.calls[0]["cmd"][2]
        assert prompt.startswith("Lies die Datei ")
        assert prompt.endswith(" und arbeite sie vollstaendig ab.")

    def test_oldest_job_is_taken_without_an_id(self, runner, board, monkeypatch, fake_run):
        import os

        board.submit("alt", "a")
        board.submit("neu", "b")
        os.utime(board.paths("alt").job_file, (1_000_000, 1_000_000))
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        assert runner.run()["job_id"] == "alt"

    def test_timeout_is_reported_as_failed(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr(
            "coma.spawn.subprocess.run",
            fake_run(raises=subprocess.TimeoutExpired(cmd="claude", timeout=30)),
        )
        result = runner.run("testjob")
        assert result["status"]["state"] == "failed"
        assert result["status"]["exit_code"] == -1
        assert job.job_file.is_file()

    def test_finalize_is_idempotent(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        result = runner.run("testjob")
        again = runner.finalize(board.paths("testjob"), result)
        assert again["status"]["state"] == "done"
        assert again["archived"] == str(job.done_file)


class TestStartAndHandle:
    def test_poll_finalizes_only_once_the_process_ended(
        self, runner, board, job, monkeypatch, fake_popen
    ):
        monkeypatch.setattr(
            "coma.spawn.subprocess.Popen",
            lambda cmd, **kw: fake_popen(cmd, **kw).program(None, 0),
        )
        handle = runner.start("testjob")
        assert handle.job_id == "testjob"
        assert handle.poll() is None
        assert state(board.paths("testjob")) == "running"
        result = handle.poll()
        assert result["status"]["state"] == "done"
        assert handle.poll() is result

    def test_wait_finalizes(self, runner, board, job, monkeypatch, fake_popen):
        monkeypatch.setattr(
            "coma.spawn.subprocess.Popen",
            lambda cmd, **kw: fake_popen(cmd, **kw).program(1),
        )
        assert runner.start("testjob").wait()["status"]["state"] == "failed"


class TestDryRun:
    def test_builds_everything_and_starts_nothing(
        self, runner, board, job, monkeypatch
    ):
        def forbidden(*args, **kwargs):  # pragma: no cover - darf nicht passieren
            raise AssertionError("dry_run darf keinen Prozess starten")

        monkeypatch.setattr("coma.spawn.subprocess.run", forbidden)
        monkeypatch.setattr("coma.spawn.subprocess.Popen", forbidden)
        plan = runner.dry_run("testjob")
        assert plan["argv"][0] == "claude"
        assert plan["verified"] is True
        assert "claude" in plan["rendered"]
        # Kein Status, kein Log — nichts wurde angefasst.
        assert not job.status_file.exists()
        assert not job.console_log.exists()


class TestPollHelpers:
    def test_read_status_accepts_paths_and_files(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        runner.run("testjob")
        paths = board.paths("testjob")
        assert read_status(paths)["state"] == "done"
        assert read_status(paths.status_file)["state"] == "done"
        assert read_status(board.paths("gibtsnicht")) is None

    def test_is_running_and_is_finished(self, board, job):
        paths = board.paths("testjob")
        from coma import StatusWriter

        writer = StatusWriter(paths.status_file)
        writer.start("testjob", "opus", paths.job_file, paths.result_file)
        assert is_running(paths) and not is_finished(paths)
        writer.finish(0)
        assert is_finished(paths) and not is_running(paths)

    def test_read_result_and_log(self, board, job):
        paths = board.paths("testjob")
        assert read_result(paths) is None
        paths.result_file.write_text("Antwort\n", encoding="utf-8")
        assert read_result(paths) == "Antwort\n"
        assert read_console_log(paths) == ""
        paths.console_log.write_text("Protokoll\n", encoding="utf-8")
        assert "Protokoll" in read_console_log(paths)

    def test_console_log_tail_is_limited(self, board, job):
        paths = board.paths("testjob")
        paths.console_log.write_text("x" * 1000, encoding="utf-8")
        assert len(read_console_log(paths, tail_bytes=50)) == 50

    def test_wait_for_finish_returns_the_final_status(self, board, job):
        from coma import StatusWriter

        paths = board.paths("testjob")
        writer = StatusWriter(paths.status_file)
        writer.start("testjob", "opus", paths.job_file, paths.result_file)
        writer.finish(0)
        assert wait_for_finish(paths, timeout=1, interval=0.01)["state"] == "done"

    def test_wait_for_finish_times_out_without_killing_anything(self, board, job):
        from coma import StatusWriter

        paths = board.paths("testjob")
        StatusWriter(paths.status_file).start(
            "testjob", "opus", paths.job_file, paths.result_file
        )
        with pytest.raises(TimeoutError, match="testjob"):
            wait_for_finish(paths, timeout=0.05, interval=0.01)
        # Der Lauf gilt weiterhin als laufend — nur das Warten wurde abgebrochen.
        assert state(paths) == "running"

    def test_wait_for_finish_rejects_zero_interval(self, board, job):
        with pytest.raises(ValueError, match="interval"):
            wait_for_finish(board.paths("testjob"), interval=0)

    def test_job_view_and_overview(self, runner, board, job, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        runner.run("testjob")
        view = job_view(board.paths("testjob"))
        assert view["state"] == "done"
        assert view["archived"] is True
        assert view["pending"] is False
        assert view["to_agent"] == 0
        rows = overview(board)
        assert [row["job_id"] for row in rows] == ["testjob"]
