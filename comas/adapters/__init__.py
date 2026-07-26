"""CLI-Adapter: pro Anbieter ein Kommando-Template plus Flags.

Der Unterschied zwischen den Anbietern ist genau das — ein Kommando-Template.
Deshalb sind es Adapter und keine Unterklassen mit eigener Prozesslogik.

Nur ``claude`` ist verifiziert. ``codex``, ``agy`` und ``kimi`` sind Geruest mit
dokumentierter Aufrufkonvention: der Kommandobau ist getestet, der scharfe
Aufrufweg nicht. :class:`comas.spawn.Spawner` startet sie nur mit
ausdruecklichem ``allow_unverified=True``.
"""
from __future__ import annotations

from typing import Any

from .agy import AgyAdapter
from .base import AdapterError, CliAdapter, SpawnSpec, join_tools, normalize_tool_list
from .claude import (
    DEFAULT_ALLOWED_TOOLS,
    KNOWN_OUTPUT_FORMATS,
    KNOWN_PERMISSION_MODES,
    MIRROR,
    NO_RESTRICTION,
    READ_ONLY_TOOLS,
    ClaudeAdapter,
)
from .codex import CodexAdapter
from .kimi import KimiAdapter

#: Name -> Klasse. Eine Registry, damit CLI und Konsumenten denselben Namen nutzen.
ADAPTERS: dict[str, type[CliAdapter]] = {
    ClaudeAdapter.name: ClaudeAdapter,
    CodexAdapter.name: CodexAdapter,
    AgyAdapter.name: AgyAdapter,
    KimiAdapter.name: KimiAdapter,
}

DEFAULT_ADAPTER = ClaudeAdapter.name


def adapter_names() -> list[str]:
    return sorted(ADAPTERS)


def get_adapter_class(name: str) -> type[CliAdapter]:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise AdapterError(
            f"unbekannter Adapter {name!r} — bekannt: {', '.join(adapter_names())}"
        ) from None


def get_adapter(name: str = DEFAULT_ADAPTER, **kwargs: Any) -> CliAdapter:
    """Adapter nach Namen erzeugen."""
    return get_adapter_class(name)(**kwargs)


def describe_adapters() -> list[dict[str, Any]]:
    """Selbstauskunft aller Adapter — Grundlage von ``comas adapters``."""
    return [cls().describe() for _, cls in sorted(ADAPTERS.items())]


__all__ = [
    "ADAPTERS",
    "DEFAULT_ADAPTER",
    "DEFAULT_ALLOWED_TOOLS",
    "KNOWN_OUTPUT_FORMATS",
    "KNOWN_PERMISSION_MODES",
    "MIRROR",
    "NO_RESTRICTION",
    "READ_ONLY_TOOLS",
    "AdapterError",
    "AgyAdapter",
    "ClaudeAdapter",
    "CliAdapter",
    "CodexAdapter",
    "KimiAdapter",
    "SpawnSpec",
    "adapter_names",
    "describe_adapters",
    "get_adapter",
    "get_adapter_class",
    "join_tools",
    "normalize_tool_list",
]
