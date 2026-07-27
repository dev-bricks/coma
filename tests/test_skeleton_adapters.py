# -*- coding: utf-8 -*-
"""Die Geruest-Adapter: Kommandobau geprueft, Aufrufweg ausdruecklich nicht.

Diese drei sind nach Auftrag **nicht live zu testen**. Geprueft wird deshalb nur,
dass sie die dokumentierte Aufrufkonvention korrekt zusammenbauen — und dass die
Sicherung greift, die sie von einem unbeaufsichtigten Lauf trennt.
"""
import pytest

from coma import Spawner, UnverifiedAdapterError
from coma.adapters import (
    AdapterError,
    AgyAdapter,
    ClaudeAdapter,
    CodexAdapter,
    KimiAdapter,
    adapter_names,
    describe_adapters,
    get_adapter,
)

SKELETONS = (KimiAdapter,)


class TestRegistry:
    def test_all_four_adapters_are_registered(self):
        assert adapter_names() == ["agy", "claude", "codex", "kimi"]

    def test_claude_codex_and_agy_are_verified(self):
        verified = {row["name"] for row in describe_adapters() if row["verified"]}
        assert verified == {"claude", "codex", "agy"}

    def test_get_adapter_by_name(self):
        assert isinstance(get_adapter("codex"), CodexAdapter)

    def test_unknown_name_is_rejected(self):
        with pytest.raises(AdapterError, match="unbekannter Adapter"):
            get_adapter("gpt42")

    @pytest.mark.parametrize("cls", SKELETONS)
    def test_each_skeleton_says_so_in_its_notes(self, cls):
        assert any("GERUEST" in note for note in cls.notes)


class TestSpawnerGuard:
    """Die Sicherung: ungetesteter Aufrufweg nicht versehentlich scharf."""

    @pytest.mark.parametrize("cls", SKELETONS)
    def test_spawner_refuses_unverified_adapters(self, cls):
        spawner = Spawner(cls())
        with pytest.raises(UnverifiedAdapterError, match="nicht live geprueft"):
            spawner.run("Hallo")

    @pytest.mark.parametrize("cls", SKELETONS)
    def test_explicit_opt_in_lets_the_call_through(self, cls, monkeypatch, fake_run):
        # subprocess wird ersetzt: agy.exe existiert auf diesem Rechner wirklich,
        # und diese Adapter sollen laut Auftrag NICHT live laufen.
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        result = Spawner(cls(), allow_unverified=True).run("Hallo")
        assert result["returncode"] == 0
        assert result["adapter"] == cls.name

    def test_claude_needs_no_opt_in(self, monkeypatch, fake_run):
        monkeypatch.setattr("coma.spawn.subprocess.run", fake_run(returncode=0))
        assert Spawner(ClaudeAdapter()).run("Hallo")["success"] is True


class TestCodex:
    def test_uses_native_exec_via_windows_node_entrypoint(self):
        cmd = CodexAdapter().build_cmd("Mach was")
        assert cmd[0] == "node"
        assert "@openai/codex/bin/codex.js" in cmd[1].replace("\\", "/")
        assert cmd[2] == "exec"
        assert cmd[-1] == "Mach was"

    def test_read_only_by_default(self):
        cmd = CodexAdapter().build_cmd("Mach was")
        assert cmd[cmd.index("--sandbox") + 1] == "read-only"

    def test_write_flag_enables_file_output(self):
        cmd = CodexAdapter(write=True).build_cmd("Mach was")
        assert cmd[cmd.index("--sandbox") + 1] == "workspace-write"

    def test_effort_and_cwd(self):
        cmd = CodexAdapter(effort="xhigh", cwd=r"C:\projekt").build_cmd("Mach was")
        assert 'model_reasoning_effort="xhigh"' in cmd
        assert cmd[cmd.index("-C") + 1] == r"C:\projekt"

    def test_unknown_effort_is_rejected(self):
        with pytest.raises(AdapterError, match="effort"):
            CodexAdapter(effort="impossible")

    def test_pointer_prompt_names_the_result_file(self):
        prompt = CodexAdapter().pointer_prompt("IN/job.md", "OUT/job.result.md")
        assert "IN/job.md" in prompt

    def test_output_last_message_uses_protocol_result_file(self):
        cmd = CodexAdapter().build_cmd(
            "Mach was", result_file="OUT/job.result.md"
        )
        assert cmd[cmd.index("--output-last-message") + 1] == "OUT/job.result.md"


class TestAgy:
    def test_workspace_scope_and_permission_are_separate_flags(self):
        cmd = AgyAdapter(add_dirs=[r"C:\ziel"]).build_cmd("do it")
        assert "--dangerously-skip-permissions" in cmd
        assert cmd[cmd.index("--add-dir") + 1] == r"C:\ziel"

    def test_one_add_dir_per_directory(self):
        cmd = AgyAdapter(add_dirs=["a", "b"]).build_cmd("do it")
        assert cmd.count("--add-dir") == 2

    def test_prompt_comes_last_after_p(self):
        cmd = AgyAdapter().build_cmd("do it")
        assert cmd[-2:] == ["-p", "do it"]

    def test_current_verified_default_model(self):
        cmd = AgyAdapter().build_cmd("do it")
        assert cmd[cmd.index("--model") + 1] == "Gemini 3.6 Flash (High)"

    def test_executable_is_the_exe_not_a_cmd(self):
        assert AgyAdapter().executable.lower().endswith("agy.exe")

    def test_pointer_prompt_requires_a_result_file(self):
        # agy gibt keinen stdout aus — ohne Zieldatei waere das Ergebnis verloren.
        with pytest.raises(AdapterError, match="result_file"):
            AgyAdapter().pointer_prompt("IN/job.md")

    def test_pointer_prompt_with_result_file(self):
        prompt = AgyAdapter().pointer_prompt("IN/job.md", "OUT/job.result.md")
        assert "OUT/job.result.md" in prompt


class TestKimi:
    def test_prompt_directly_after_p(self):
        cmd = KimiAdapter().build_cmd("mach was")
        index = cmd.index("-p")
        assert cmd[index:index + 2] == ["-p", "mach was"]

    def test_windows_uses_node_entrypoint(self):
        cmd = KimiAdapter().build_cmd("mach was")
        assert cmd[0] == "node"
        assert "@moonshot-ai/kimi-code" in cmd[1].replace("\\", "/")

    @pytest.mark.parametrize("flag", ["-y", "--yolo", "--auto"])
    def test_incompatible_flags_are_refused(self, flag):
        with pytest.raises(AdapterError, match="nicht mit"):
            KimiAdapter(extra_args=[flag]).build_cmd("mach was")

    def test_model_and_session(self):
        cmd = KimiAdapter(model="k2", session="abc").build_cmd("mach was")
        assert cmd[cmd.index("-m") + 1] == "k2"
        assert cmd[cmd.index("-S") + 1] == "abc"

    def test_unknown_output_format_is_rejected(self):
        with pytest.raises(AdapterError, match="output_format"):
            KimiAdapter(output_format="json")
