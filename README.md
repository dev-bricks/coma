![COMA Banner](docs/assets/banner.svg)

# COMA — Command & Communication for Autonomous Agents

**[English](README.md) | [Deutsch](README_de.md)**

[![Pytest Status](https://img.shields.io/badge/pytest-233%20passed-brightgreen.svg)](https://docs.pytest.org/)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Organization: ellmos-ai](https://img.shields.io/badge/organization-ellmos--ai-blue.svg)](https://github.com/ellmos-ai)
[![Umbrella: open-bricks](https://img.shields.io/badge/umbrella-open--bricks-purple.svg)](https://github.com/open-bricks)

> [!NOTE]
> **LLM / AI Context Index:** For an AI-optimized specification and architecture overview, see [`llms.txt`](llms.txt).

> **Name Migration Notice:** The project and canonical Python package are named `COMA` / `coma`. The legacy name `COMAS`/`comas` remains available during a transition period as an import and CLI alias; new integrations must use `coma`.

> **The Agent Lifecycle Layer:** How is an autonomous AI agent spawned as a standalone process, and how do you communicate with it while it runs?

COMA is a **session-decoupled communication channel and process spawner for AI agents** (file-system based via `IN/`, `OUT/`, `DONE/`). The name stands for **Command & Communication for Agents**.

Single responsibility: COMA does not handle permissions, locks, or long-term agent memory. It works strictly with local files and standard OS processes—**no account required, no network services, no cluster dependencies**. Zero third-party dependencies, standard library only.

See [`KONZEPT.md`](KONZEPT.md) for background details and architectural decisions.

```mermaid
flowchart TD
    subgraph Client ["Orchestrator / Client Session"]
        A[JobBoard.submit] -->|Writes job prompt| B["IN/<jobid>.md"]
    end
    
    subgraph COMA ["COMA Agent Spawner"]
        B --> C{JobRunner / Spawner}
        C -->|Selects CLI Adapter| D[Claude / Codex / AGY / Kimi Adapter]
        D -->|Spawns Subprocess| E[Local Agent Process]
    end

    subgraph Agent ["Agent Execution"]
        E -->|Stream progress events| F["OUT/coma.<jobid>.from-agent.jsonl"]
        E -->|Write final output| G["OUT/<jobid>.result.md"]
    end

    subgraph Completion ["Completion Phase"]
        G --> H["OUT/coma.<jobid>.json (Status: DONE)"]
        H --> I["Move IN/<jobid>.md -> DONE/<jobid>.md"]
    end
```

| Layer | Core Question | Handled By |
|---|---|---|
| **Lifecycle & Communication** | How to spawn an agent and stream input/output? | **COMA** |
| Access Control & Locks | Who can touch which resource/repo? | `lock-master` → Roshambo |
| Memory & History | Was this attempted before, what was the outcome? | Roshambo |

Separation of verbs: COMA uses `spawn`, `send`, `poll`, `result`. A coordinator uses `claim`, `release`, `remember`, `recall`, `decide`, `status`. No overlap.

## Use Cases

1. **Decoupling from Remote Control (RC) Sessions**
   In interactive remote-control sessions, CLI permission bypass flags like `--dangerously-skip-permissions` may fail to pass through to remote clients. COMA launches the agent as an independent OS process outside the RC session, communicating cleanly via file-system channels.

2. **Session-Independent Handoffs & Relays**
   Tasks can be handed off across session boundaries between agents without blocking process threads or losing context.

3. **Background Job Execution**
   File-system based queueing (`IN/`, `OUT/`, `DONE/`) for autonomous background runners and decoupled tool executions.

## Quickstart

```python
from coma import JobBoard, JobRunner

board = JobBoard(r"C:\Users\user\_agentjobs")
board.submit("myjob", "# Instructions\nWrite result to OUT/myjob.result.md.\n")

result = JobRunner(board).run("myjob")
print(result["status"]["state"], result["result_written"])
```

Or from the command line:

```bat
coma --root C:\Users\user\_agentjobs run myjob
coma --root C:\Users\user\_agentjobs run myjob --dry-run   :: preview command without launching
coma --root C:\Users\user\_agentjobs status myjob
coma --root C:\Users\user\_agentjobs result myjob
```

## Job Protocol

```
IN/    <jobid>.md                       Job prompt (Markdown)
OUT/   <jobid>.result.md                Final agent result output
       coma.<jobid>.json               Runner status (written by runner only)
       coma.<jobid>.from-agent.jsonl   Progress stream (written by agent only)
       coma.<jobid>.to-agent.jsonl     Instruction stream (written by orchestrator only)
       coma.<jobid>.console.log        Combined stdout / stderr log
DONE/  <jobid>.md                       Completed job prompt
```

**Single writer per file:** No locking required, structural collision prevention.

## Spawner Layer

Adapters encapsulate CLI arguments for specific agent engines:

```python
from coma import ClaudeAdapter, Spawner

adapter = ClaudeAdapter(model="sonnet", permission_mode="dontAsk",
                        allowed_tools=["Read", "Write"], max_budget_usd=2.0)
print(adapter.build_cmd("Say Hello"))   # Returns argument list without running

spawner = Spawner(adapter)
result = spawner.run("Say Hello", log_file="run.log")
```

### Verified Adapters

| Adapter | Target Engine | Status |
|---|---|---|
| `claude` | Anthropic Claude Code CLI | **Verified** — Flags checked against `claude --help` 2.1.220 |
| `codex` | OpenAI Codex CLI | **Verified** — Tested against CLI 0.145.0 |
| `agy` | Google Antigravity / AGY CLI | **Verified** — Tested against agy 1.1.7 |
| `kimi` | Kimi Code CLI | **Skeleton** — CLI 0.29.2 detected |

## CLI Commands

| Command | Purpose |
|---|---|
| `run [jobid]` | Execute job from queue |
| `run ... --dry-run` | Build and show command string without executing |
| `cmd <prompt>` | Show command string for custom prompt |
| `submit <jobid>` | Submit job prompt into `IN/` |
| `status <jobid>` · `list` | Check status of job(s) |
| `result <jobid>` · `log <jobid>` | Read result output or console log |
| `send <jobid> <text>` · `inbox <jobid>` | Send message or read progress stream |
| `adapters` | Show adapter status & detected binaries |
| `check` · `vendor` | Verify or build vendor manifest |

## Testing

```bat
python -m pytest -q      :: 233 passed tests
```

Tests use mocked subprocesses to ensure fast, deterministic verification with 0 token consumption.

## License

MIT License. Developed under the `ellmos-ai` / `open-bricks` ecosystem.
