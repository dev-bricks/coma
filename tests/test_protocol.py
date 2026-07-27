# -*- coding: utf-8 -*-
"""Protokoll: Dateinamen, Reihenfolge, Archivierung.

Die Dateinamen sind hier keine Geschmacksfrage — sie muessen zeichengenau denen
der Startschale entsprechen, sonst lesen ``.bat`` und Python-Schicht
verschiedene Artefakte.
"""
import time

import pytest

from coma import JobBoard, JobNotFound, JobPaths, ProtocolError, check_job_id


class TestJobId:
    @pytest.mark.parametrize(
        "job_id", ["selftest", "T-20260726-01", "coma_modul.v2", "a"]
    )
    def test_accepted(self, job_id):
        assert check_job_id(job_id) == job_id

    @pytest.mark.parametrize(
        "job_id",
        ["", "..", "../flucht", "unter/ordner", r"unter\ordner", "-start", "job.md", None],
    )
    def test_rejected(self, job_id):
        with pytest.raises(ProtocolError):
            check_job_id(job_id)


class TestPaths:
    def test_names_match_the_startschale(self, tmp_path):
        paths = JobPaths(tmp_path, "selftest")
        assert paths.job_file == tmp_path / "IN" / "selftest.md"
        assert paths.result_file == tmp_path / "OUT" / "selftest.result.md"
        assert paths.status_file == tmp_path / "OUT" / "coma.selftest.json"
        assert (
            paths.from_agent_file
            == tmp_path / "OUT" / "coma.selftest.from-agent.jsonl"
        )
        assert paths.to_agent_file == tmp_path / "OUT" / "coma.selftest.to-agent.jsonl"
        assert paths.console_log == tmp_path / "OUT" / "coma.selftest.console.log"
        assert paths.done_file == tmp_path / "DONE" / "selftest.md"

    def test_as_dict_covers_every_artefact(self, tmp_path):
        keys = set(JobPaths(tmp_path, "x").as_dict())
        assert keys == {
            "root",
            "job_id",
            "job_file",
            "result_file",
            "status_file",
            "from_agent_file",
            "to_agent_file",
            "console_log",
            "done_file",
        }


class TestBoard:
    def test_ensure_dirs_creates_all_three(self, tmp_path):
        board = JobBoard(tmp_path / "jobs")
        board.ensure_dirs()
        for name in ("IN", "OUT", "DONE"):
            assert (tmp_path / "jobs" / name).is_dir()

    def test_submit_writes_the_job_file(self, board):
        paths = board.submit("neu", "# Auftrag\n")
        assert paths.job_file.read_text(encoding="utf-8") == "# Auftrag\n"

    def test_submit_refuses_to_overwrite(self, board):
        board.submit("neu", "eins")
        with pytest.raises(ProtocolError, match="existiert bereits"):
            board.submit("neu", "zwei")
        board.submit("neu", "zwei", overwrite=True)
        assert board.paths("neu").job_file.read_text(encoding="utf-8") == "zwei"

    def test_pending_is_oldest_first(self, board):
        board.submit("zuerst", "a")
        time.sleep(0.02)
        board.submit("danach", "b")
        # mtime explizit setzen, damit der Test nicht von der Uhr abhaengt.
        import os

        old = board.paths("zuerst").job_file
        os.utime(old, (1_000_000, 1_000_000))
        assert board.pending()[0] == "zuerst"
        assert board.oldest_pending() == "zuerst"

    def test_pending_on_missing_directory_is_empty(self, tmp_path):
        assert JobBoard(tmp_path / "gibtsnicht").pending() == []

    def test_resolve_without_id_takes_the_oldest(self, board):
        board.submit("einziger", "a")
        assert board.resolve(None).job_id == "einziger"

    def test_resolve_without_jobs_raises(self, board):
        with pytest.raises(JobNotFound, match="keine Auftraege"):
            board.resolve(None)

    def test_resolve_unknown_id_raises(self, board):
        with pytest.raises(JobNotFound, match="nicht gefunden"):
            board.resolve("gibtsnicht")

    def test_archive_moves_to_done(self, board, job):
        target = board.archive("testjob")
        assert target == board.paths("testjob").done_file
        assert target.is_file()
        assert not job.job_file.exists()

    def test_archive_overwrites_like_move_y(self, board, job):
        board.paths("testjob").done_dir.mkdir(exist_ok=True)
        board.paths("testjob").done_file.write_text("alt", encoding="utf-8")
        board.archive("testjob")
        assert "Auftrag" in board.paths("testjob").done_file.read_text(encoding="utf-8")

    def test_archive_without_job_raises(self, board):
        with pytest.raises(JobNotFound, match="nichts zu archivieren"):
            board.archive("gibtsnicht")

    def test_known_jobs_includes_status_only_jobs(self, board, job):
        board.paths("nurstatus").status_file.write_text("{}", encoding="utf-8")
        board.submit("offen", "x")
        board.archive("testjob")
        assert board.known_jobs() == ["nurstatus", "offen", "testjob"]
