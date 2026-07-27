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
