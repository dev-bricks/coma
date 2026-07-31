"""Compatibility coverage for the former COMAS package name."""
from __future__ import annotations

import importlib

import pytest


def test_old_package_name_reexports_public_api() -> None:
    with pytest.deprecated_call(match="renamed to 'coma'"):
        legacy = importlib.import_module("comas")

    canonical = importlib.import_module("coma")
    assert legacy.JobBoard is canonical.JobBoard
    assert legacy.__version__ == canonical.__version__


def test_old_submodule_name_resolves() -> None:
    legacy = importlib.import_module("comas.manifest")
    canonical = importlib.import_module("coma.manifest")
    assert legacy.build_manifest is canonical.build_manifest


def test_old_status_and_cli_submodules_resolve() -> None:
    comas_status = importlib.import_module("comas.status")
    coma_status = importlib.import_module("coma.status")
    assert comas_status.main is coma_status.main

    comas_cli = importlib.import_module("comas.cli")
    coma_cli = importlib.import_module("coma.cli")
    assert comas_cli.main is coma_cli.main


def test_old_adapters_and_channels_submodules_resolve() -> None:
    comas_adapters = importlib.import_module("comas.adapters")
    coma_adapters = importlib.import_module("coma.adapters")
    assert comas_adapters.CliAdapter is coma_adapters.CliAdapter

    comas_claude = importlib.import_module("comas.adapters.claude")
    coma_claude = importlib.import_module("coma.adapters.claude")
    assert comas_claude.ClaudeAdapter is coma_claude.ClaudeAdapter

    comas_channels = importlib.import_module("comas.channels")
    coma_channels = importlib.import_module("coma.channels")
    assert comas_channels.ChannelError is coma_channels.ChannelError
