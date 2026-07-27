"""Compatibility import for the former :mod:`comas` package name.

COMA is the canonical package. This shim keeps existing integrations working
for one migration period while emitting a deprecation warning.
"""
from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "'comas' was renamed to 'coma'; update imports and CLI calls.",
    DeprecationWarning,
    stacklevel=2,
)

from coma import *  # noqa: F401,F403
from coma import __all__, __version__

_MODULES = (
    "adapters",
    "adapters.agy",
    "adapters.base",
    "adapters.claude",
    "adapters.codex",
    "adapters.kimi",
    "channels",
    "cli",
    "locks",
    "manifest",
    "poll",
    "protocol",
    "runner",
    "spawn",
)

for _name in _MODULES:
    sys.modules[f"{__name__}.{_name}"] = importlib.import_module(f"coma.{_name}")
