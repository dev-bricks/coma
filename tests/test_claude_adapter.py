# -*- coding: utf-8 -*-
"""Kommandobau des claude-Adapters — gegen erwartete Argumentlisten, ohne Prozess.

Kein Test hier startet etwas. Geprueft wird die Argumentliste, die
:meth:`ClaudeAdapter.build_cmd` erzeugt (Vorbild: ``swarm-ai/tests/test_runner.py``,
das mit Mocks arbeitet).
"""
import pytest

from comas.adapters import (
    DEFAULT_ALLOWED_TOOLS,
    KNOWN_PERMISSION_MODES,
    MIRROR,
    NO_RESTRICTION,
    READ_ONLY_TOOLS,
    AdapterError,
    ClaudeAdapter,
)


def flag_value(cmd, flag):
    """Der Wert direkt hinter einem Flag."""
    return cmd[cmd.index(flag) + 1]


class TestDefaults:
    def test_defaults_stem_from_the_bat_and_llmauto(self):
        adapter = ClaudeAdapter()
        assert adapter.model == "opus"  # START-LOCAL-AGENT.bat:34
        assert adapter.permission_mode == "dontAsk"  # KONZEPT.md Lektion 4
        assert adapter.allowed_tools == list(DEFAULT_ALLOWED_TOOLS)
        assert adapter.available_tools is MIRROR
        assert adapter.allow_mcp is False
        assert adapter.persist_sessions is False
        assert adapter.verified is True

    def test_default_command(self):
        cmd = ClaudeAdapter().build_cmd("Hallo")
        assert cmd[0] == "claude"
        assert flag_value(cmd, "--model") == "opus"
        assert flag_value(cmd, "--permission-mode") == "dontAsk"
        assert flag_value(cmd, "--tools") == "Read,Edit,Write,Bash,Glob,Grep"
        assert flag_value(cmd, "--allowedTools") == "Read,Edit,Write,Bash,Glob,Grep"
        assert flag_value(cmd, "--disallowedTools") == "mcp__*"
        assert "--no-session-persistence" in cmd

    def test_empty_prompt_is_rejected(self):
        for bad in ("", "   ", None, 42):
            with pytest.raises(AdapterError, match="prompt"):
                ClaudeAdapter().build_cmd(bad)


class TestArgumentOrder:
    """Der Grund fuer die Reihenfolge ist eine Falle, nicht Geschmack."""

    def test_prompt_stands_directly_after_p(self):
        cmd = ClaudeAdapter().build_cmd("Mein Prompt")
        assert cmd[1] == "-p"
        assert cmd[2] == "Mein Prompt"

    def test_prompt_never_follows_a_variadic_flag(self):
        # --tools, --allowedTools und --disallowedTools sind <tools...>. Stuende
        # der Prompt dahinter, wuerde er als Werkzeugname verschluckt.
        variadic = {"--tools", "--allowedTools", "--disallowedTools"}
        cmd = ClaudeAdapter(
            output_format="stream-json", max_budget_usd=1.5, fallback_model="sonnet"
        ).build_cmd("Mein Prompt")
        prompt_index = cmd.index("Mein Prompt")
        assert prompt_index == 2
        for flag in variadic:
            if flag in cmd:
                assert cmd.index(flag) > prompt_index

    def test_tool_lists_are_one_argument_each(self):
        cmd = ClaudeAdapter(allowed_tools=["Read", "Write"]).build_cmd("Hallo")
        index = cmd.index("--allowedTools")
        assert cmd[index + 1] == "Read,Write"
        # Das naechste Element ist wieder ein Flag, kein Werkzeugname.
        assert cmd[index + 2].startswith("--")


class TestUnionOfCapabilities:
    """Die Abnahmebedingung: alle Faehigkeiten der drei Quellen sind erreichbar."""

    REQUIRED_FLAGS = (
        "--fallback-model",
        "--continue",
        "--max-budget-usd",
        "--output-format",
        "--permission-mode",
        "--allowedTools",
        "--disallowedTools",
        "--tools",
        "--no-session-persistence",
        "--safe-mode",
        "--verbose",
        "--model",
    )

    def test_every_flag_is_reachable_through_the_api(self):
        cmd = ClaudeAdapter(
            model="sonnet",
            fallback_model="haiku",
            permission_mode="bypassPermissions",
            allowed_tools=["Read", "Write"],
            available_tools=["Read", "Write", "Bash"],
            disallowed_tools=["mcp__*", "WebSearch"],
            persist_sessions=False,
            safe_mode=True,
            output_format="json",
            verbose=True,
            max_budget_usd=2.5,
            continue_conversation=True,
        ).build_cmd("Hallo")
        for flag in self.REQUIRED_FLAGS:
            assert flag in cmd, f"{flag} fehlt in {cmd}"
        assert flag_value(cmd, "--disallowedTools") == "mcp__*,WebSearch"
        assert flag_value(cmd, "--max-budget-usd") == "2.5"

    def test_overrides_work_per_call(self):
        adapter = ClaudeAdapter(model="opus")
        cmd = adapter.build_cmd("Hallo", model="haiku", permission_mode="acceptEdits")
        assert flag_value(cmd, "--model") == "haiku"
        assert flag_value(cmd, "--permission-mode") == "acceptEdits"
        # Der Adapter selbst bleibt unveraendert.
        assert adapter.model == "opus"

    def test_extra_args_are_appended(self):
        cmd = ClaudeAdapter(extra_args=["--effort", "high"]).build_cmd("Hallo")
        assert cmd[-2:] == ["--effort", "high"]


class TestStreamJsonCoupling:
    """stream-json ohne --verbose stirbt zur Laufzeit — also wird es erzwungen."""

    def test_stream_json_forces_verbose(self):
        cmd = ClaudeAdapter(output_format="stream-json").build_cmd("Hallo")
        assert flag_value(cmd, "--output-format") == "stream-json"
        assert "--verbose" in cmd

    def test_stream_json_via_override_also_forces_verbose(self):
        cmd = ClaudeAdapter().build_cmd("Hallo", output_format="stream-json")
        assert "--verbose" in cmd

    def test_other_formats_do_not_force_verbose(self):
        for fmt in ("text", "json"):
            cmd = ClaudeAdapter(output_format=fmt).build_cmd("Hallo")
            assert "--verbose" not in cmd

    def test_unknown_format_is_rejected(self):
        with pytest.raises(AdapterError, match="output_format"):
            ClaudeAdapter(output_format="yaml")


class TestToolSemantics:
    def test_no_restriction_omits_both_flags(self):
        cmd = ClaudeAdapter(
            allowed_tools=NO_RESTRICTION, available_tools=NO_RESTRICTION
        ).build_cmd("Hallo")
        assert "--tools" not in cmd
        assert "--allowedTools" not in cmd

    def test_none_behaves_like_no_restriction(self):
        cmd = ClaudeAdapter(allowed_tools=None, available_tools=None).build_cmd("Hallo")
        assert "--tools" not in cmd
        assert "--allowedTools" not in cmd

    def test_empty_available_list_disables_all_builtins(self):
        cmd = ClaudeAdapter(allowed_tools=[], available_tools=[]).build_cmd("Hallo")
        assert flag_value(cmd, "--tools") == ""
        assert "--allowedTools" not in cmd

    def test_available_mirrors_allowed_by_default(self):
        cmd = ClaudeAdapter(allowed_tools=["Read"]).build_cmd("Hallo")
        assert flag_value(cmd, "--tools") == "Read"
        assert flag_value(cmd, "--allowedTools") == "Read"

    def test_available_can_differ_from_allowed(self):
        cmd = ClaudeAdapter(
            allowed_tools=["Read"], available_tools=["Read", "Bash"]
        ).build_cmd("Hallo")
        assert flag_value(cmd, "--tools") == "Read,Bash"
        assert flag_value(cmd, "--allowedTools") == "Read"

    def test_override_of_allowed_also_mirrors(self):
        cmd = ClaudeAdapter().build_cmd("Hallo", allowed_tools=["Read"])
        assert flag_value(cmd, "--tools") == "Read"

    def test_string_instead_of_sequence_is_rejected(self):
        with pytest.raises(TypeError, match="Sequenz"):
            ClaudeAdapter(allowed_tools="Read")

    def test_allow_mcp_drops_the_deny_rule(self):
        cmd = ClaudeAdapter(allow_mcp=True).build_cmd("Hallo")
        assert "--disallowedTools" not in cmd


class TestPermissionModeStaysAParameter:
    """Der Permission-Mode ist ein Sicherheitsprofil und darf nie fest sein."""

    @pytest.mark.parametrize("mode", KNOWN_PERMISSION_MODES)
    def test_every_known_mode_is_accepted(self, mode):
        cmd = ClaudeAdapter(permission_mode=mode).build_cmd("Hallo")
        assert flag_value(cmd, "--permission-mode") == mode

    def test_typo_is_caught_before_the_process_starts(self):
        with pytest.raises(AdapterError, match="permission_mode"):
            ClaudeAdapter(permission_mode="dontask")

    def test_strict_check_can_be_switched_off_for_newer_clis(self):
        cmd = ClaudeAdapter(
            permission_mode="zukunftsModus", strict_permission_modes=False
        ).build_cmd("Hallo")
        assert flag_value(cmd, "--permission-mode") == "zukunftsModus"


class TestPresets:
    def test_unattended_is_the_default(self):
        assert ClaudeAdapter.preset("unattended").build_cmd("x") == ClaudeAdapter().build_cmd("x")

    def test_read_only_matches_the_swarm_profile(self):
        adapter = ClaudeAdapter.preset("read_only")
        assert adapter.allowed_tools == list(READ_ONLY_TOOLS)
        cmd = adapter.build_cmd("Hallo")
        assert flag_value(cmd, "--allowedTools") == "Read,Glob,Grep"
        assert "Write" not in flag_value(cmd, "--tools")

    def test_bat_compat_reproduces_the_verified_startschale(self):
        cmd = ClaudeAdapter.preset("bat_compat").build_cmd("Lies die Datei X")
        # START-LOCAL-AGENT.bat:72 — genau diese Bestandteile, nichts weiter.
        assert cmd == [
            "claude",
            "-p",
            "Lies die Datei X",
            "--model",
            "opus",
            "--permission-mode",
            "bypassPermissions",
        ]

    def test_preset_accepts_overrides(self):
        adapter = ClaudeAdapter.preset("read_only", model="haiku")
        assert adapter.model == "haiku"
        assert adapter.allowed_tools == list(READ_ONLY_TOOLS)

    def test_unknown_preset_is_rejected(self):
        with pytest.raises(AdapterError, match="Profil"):
            ClaudeAdapter.preset("wildwest")


class TestBudget:
    def test_rejected_at_construction(self):
        for bad in (0, -1, float("nan"), float("inf")):
            with pytest.raises(AdapterError, match="max_budget_usd"):
                ClaudeAdapter(max_budget_usd=bad)

    def test_rejected_as_override(self):
        with pytest.raises(AdapterError, match="max_budget_usd"):
            ClaudeAdapter().build_cmd("Hallo", max_budget_usd=float("nan"))


class TestEnvironment:
    def test_claudecode_is_removed(self, monkeypatch):
        monkeypatch.setenv("CLAUDECODE", "1")
        env = ClaudeAdapter().build_env()
        assert "CLAUDECODE" not in env

    def test_pythonioencoding_is_set(self):
        assert ClaudeAdapter().build_env()["PYTHONIOENCODING"] == "utf-8"

    def test_path_survives(self, monkeypatch):
        monkeypatch.setenv("PATH", "/irgendwo")
        assert ClaudeAdapter().build_env()["PATH"] == "/irgendwo"

    def test_overrides_win(self):
        env = ClaudeAdapter(env_overrides={"PYTHONIOENCODING": "latin-1"}).build_env()
        assert env["PYTHONIOENCODING"] == "latin-1"


class TestPointerPrompt:
    def test_matches_the_bat_character_for_character(self):
        prompt = ClaudeAdapter().pointer_prompt(r"C:\jobs\IN\selftest.md")
        assert prompt == (
            r"Lies die Datei C:\jobs\IN\selftest.md und arbeite sie vollstaendig ab."
        )

    def test_contains_nothing_that_needs_escaping(self):
        prompt = ClaudeAdapter().pointer_prompt("/pfad/job.md")
        for forbidden in ('"', "'", "{", "}", "\n"):
            assert forbidden not in prompt


class TestSpawnSpec:
    def test_spec_carries_everything_needed(self):
        spec = ClaudeAdapter(timeout=60).build_spec("Hallo")
        assert spec.adapter == "claude"
        assert spec.verified is True
        assert spec.timeout == 60
        assert spec.command[0] == "claude"
        assert spec.env["PYTHONIOENCODING"] == "utf-8"
        assert "claude" in spec.rendered()

    def test_rendered_quotes_arguments_with_spaces(self):
        spec = ClaudeAdapter().build_spec("zwei Woerter")
        assert '"zwei Woerter"' in spec.rendered()
