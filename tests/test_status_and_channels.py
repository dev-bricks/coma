# -*- coding: utf-8 -*-
"""Statusschreiber und Kanaele.

Der Statustest ist ein Kompatibilitaetstest: Die Schluessel muessen denen von
``_agentjobs/comas_status.py`` entsprechen, sonst lesen ``.bat`` und
Python-Schicht aneinander vorbei.
"""
import json

import pytest

from comas import Channel, ChannelError, StatusWriter, from_agent, to_agent
from comas.status import BASE_KEYS, STATE_DONE, STATE_FAILED, STATE_RUNNING, main


class TestStatusWriter:
    def test_start_writes_exactly_the_legacy_keys(self, tmp_path):
        path = tmp_path / "comas.job.json"
        data = StatusWriter(path).start("job", "opus", "IN/job.md", "OUT/job.result.md")
        assert list(data) == list(BASE_KEYS)
        assert data["state"] == STATE_RUNNING
        assert data["exit_code"] is None
        assert data["finished"] is None
        assert json.loads(path.read_text(encoding="utf-8")) == data

    def test_finish_zero_means_done(self, tmp_path):
        writer = StatusWriter(tmp_path / "s.json")
        writer.start("job", "opus", "a", "b")
        data = writer.finish(0)
        assert data["state"] == STATE_DONE
        assert data["exit_code"] == 0
        assert data["finished"] is not None

    def test_finish_nonzero_means_failed(self, tmp_path):
        writer = StatusWriter(tmp_path / "s.json")
        writer.start("job", "opus", "a", "b")
        assert writer.finish(3)["state"] == STATE_FAILED

    def test_finish_preserves_unknown_keys(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text(
            json.dumps({"job_id": "job", "fremdfeld": 42}), encoding="utf-8"
        )
        data = StatusWriter(path).finish(0)
        assert data["fremdfeld"] == 42

    def test_finish_without_file_still_writes_a_state(self, tmp_path):
        data = StatusWriter(tmp_path / "fehlt.json").finish(1)
        assert data["state"] == STATE_FAILED
        assert data["job_id"] is None

    def test_extra_fields_are_additive(self, tmp_path):
        writer = StatusWriter(tmp_path / "s.json")
        data = writer.start(
            "job", "opus", "a", "b", extra={"adapter": "claude", "argv": ["claude"]}
        )
        assert list(data)[: len(BASE_KEYS)] == list(BASE_KEYS)
        assert data["adapter"] == "claude"

    def test_read_returns_none_for_broken_json(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text("{kaputt", encoding="utf-8")
        assert StatusWriter(path).read() is None

    def test_write_is_atomic_no_tmp_left_behind(self, tmp_path):
        path = tmp_path / "s.json"
        StatusWriter(path).start("job", "opus", "a", "b")
        assert not (tmp_path / "s.json.tmp").exists()


class TestStatusCli:
    """Argv-kompatibel zur Vorlage — die ``.bat`` koennte darauf umgestellt werden."""

    def test_start_and_finish(self, tmp_path):
        path = str(tmp_path / "s.json")
        assert main(["prog", "start", path, "job", "opus", "IN/j.md", "OUT/j.md"]) == 0
        assert main(["prog", "finish", path, "0"]) == 0
        assert json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["state"] == "done"

    def test_too_few_arguments(self, tmp_path):
        assert main(["prog", "start", str(tmp_path / "s.json")]) == 2
        assert main(["prog"]) == 2

    def test_unknown_mode(self, tmp_path):
        assert main(["prog", "fliegen", str(tmp_path / "s.json")]) == 2


class TestChannels:
    def test_ensure_creates_an_empty_file(self, job):
        path = to_agent(job).ensure()
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == ""

    def test_ensure_does_not_truncate(self, job):
        channel = to_agent(job)
        channel.append({"message": "eins"})
        channel.ensure()
        assert channel.count() == 1

    def test_append_adds_a_timestamp(self, job):
        record = to_agent(job).append({"message": "hallo"})
        assert "ts" in record
        assert to_agent(job).read() == [record]

    def test_umlauts_survive(self, job):
        to_agent(job).append({"message": "Grüße, prüfen, Größe"})
        assert "Grüße" in to_agent(job).read()[0]["message"]

    def test_wrong_role_is_refused(self, job):
        with pytest.raises(ChannelError, match="orchestrator"):
            to_agent(job).append({"message": "x"}, role="agent")

    def test_right_role_passes(self, job):
        to_agent(job).append({"message": "x"}, role="orchestrator")
        from_agent(job).append({"progress": 1}, role="agent")
        assert from_agent(job).count() == 1

    def test_broken_lines_are_skipped_not_fatal(self, job):
        channel = from_agent(job)
        channel.append({"progress": 1})
        with channel.path.open("a", encoding="utf-8") as handle:
            handle.write("{halb geschrieben\n")
        channel.append({"progress": 2})
        assert [record["progress"] for record in channel.read()] == [1, 2]

    def test_tail_and_since(self, job):
        channel = from_agent(job)
        for index in range(5):
            channel.append({"n": index})
        assert [record["n"] for record in channel.tail(2)] == [3, 4]
        assert [record["n"] for record in channel.since(3)] == [3, 4]
        assert channel.tail(0) == []

    def test_missing_file_reads_as_empty(self, job):
        assert from_agent(job).read() == []

    def test_payload_must_be_a_mapping(self, job):
        with pytest.raises(TypeError, match="Mapping"):
            to_agent(job).append("nur Text")

    def test_channel_repr_names_its_writer(self, tmp_path):
        channel = Channel(tmp_path / "x.jsonl", writer_role="agent", name="from-agent")
        assert "from-agent" in repr(channel) and "agent" in repr(channel)
