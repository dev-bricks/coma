"""COMA — COMmunication for Autonomous Subagents.

Die **Lebenszyklus-Schicht** fuer Agenten: Wie entsteht ein Agent als eigener
Prozess, und wie bleibt man mit ihm in Kontakt, solange er laeuft?

Genau eine Verantwortung. COMA sperrt nichts, verwaltet keine Rechte und haelt
kein Gedaechtnis. Das Vokabular trennt sauber: COMA spricht ``spawn``, ``send``,
``poll``, ``result`` — ein Koordinator wie Roshambo spricht ``claim``,
``release``, ``remember``, ``recall``, ``decide``, ``status``.

Arbeitet mit Dateien und Prozessen: **ohne Konto, ohne Netz, ohne Cluster.**

Kurzform::

    from coma import JobBoard, JobRunner

    board = JobBoard(r"C:\\…\\_control-center\\_agentjobs")
    result = JobRunner(board).run("meinjob")
    print(result["status"]["state"], result["result_written"])

Wer nur ein Kommando braucht, ohne Jobverzeichnis::

    from coma import ClaudeAdapter, Spawner

    spawner = Spawner(ClaudeAdapter(model="sonnet"))
    print(spawner.adapter.build_cmd("Sag Hallo"))

Vollstaendige Beschreibung: ``KONZEPT.md`` und ``README.md``.
"""
from __future__ import annotations

__version__ = "0.2.0"

from .adapters import (
    ADAPTERS,
    DEFAULT_ADAPTER,
    DEFAULT_ALLOWED_TOOLS,
    KNOWN_OUTPUT_FORMATS,
    KNOWN_PERMISSION_MODES,
    MIRROR,
    NO_RESTRICTION,
    READ_ONLY_TOOLS,
    AdapterError,
    AgyAdapter,
    ClaudeAdapter,
    CliAdapter,
    CodexAdapter,
    KimiAdapter,
    SpawnSpec,
    adapter_names,
    describe_adapters,
    get_adapter,
)
from .channels import Channel, ChannelError, from_agent, to_agent
from .locks import LockBackend, LockDenied, NullLock, claimed
from .manifest import CheckReport, ManifestError, build_manifest, check_manifest, vendor
from .poll import (
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
from .protocol import (
    JobBoard,
    JobNotFound,
    JobPaths,
    ProtocolError,
    check_job_id,
)
from .runner import JobHandle, JobRunner
from .spawn import (
    ProcessHandle,
    SpawnError,
    Spawner,
    UnverifiedAdapterError,
    wait_all,
)
from .status import (
    STATE_DONE,
    STATE_FAILED,
    STATE_RUNNING,
    StatusWriter,
)

__all__ = [
    "ADAPTERS",
    "DEFAULT_ADAPTER",
    "DEFAULT_ALLOWED_TOOLS",
    "KNOWN_OUTPUT_FORMATS",
    "KNOWN_PERMISSION_MODES",
    "MIRROR",
    "NO_RESTRICTION",
    "READ_ONLY_TOOLS",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_RUNNING",
    "AdapterError",
    "AgyAdapter",
    "Channel",
    "ChannelError",
    "CheckReport",
    "ClaudeAdapter",
    "CliAdapter",
    "CodexAdapter",
    "JobBoard",
    "JobHandle",
    "JobNotFound",
    "JobPaths",
    "JobRunner",
    "KimiAdapter",
    "LockBackend",
    "LockDenied",
    "ManifestError",
    "NullLock",
    "ProcessHandle",
    "ProtocolError",
    "SpawnError",
    "SpawnSpec",
    "Spawner",
    "StatusWriter",
    "UnverifiedAdapterError",
    "__version__",
    "adapter_names",
    "build_manifest",
    "check_job_id",
    "check_manifest",
    "claimed",
    "describe_adapters",
    "from_agent",
    "get_adapter",
    "is_finished",
    "is_running",
    "job_view",
    "overview",
    "read_console_log",
    "read_result",
    "read_status",
    "state",
    "to_agent",
    "vendor",
    "wait_all",
    "wait_for_finish",
]
