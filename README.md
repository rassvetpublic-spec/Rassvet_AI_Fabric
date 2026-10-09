# Rassvet AI Fabric / 0.1.0

**Original implementation, from zero.** Windows-first development harness prototype with a transactional local queue, read-only MCP gateway, explicit task checkpoints, and opt-in worker adapters. The repository does **not** copy code from oh-my-codex, Superpowers, or the preceding `omx-app` package.

## Runtime and safety

- Python 3.11+ (standard library only at runtime), Windows 10/11 or Linux.
- SQLite task state with one transaction per task transition. Durable events and SHA-256 checkpoint readback.
- Task dependency graph, leases, heartbeat, fencing generation, cancellation request, and manual recovery after lease expiry.
- MCP stdio: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`; negotiates the **legacy 2025-11-25 / 2025-06-18 protocol**, not the newer 2026-07-28 transport.
- MCP is read-only. There is no shell execution, file write, token sharing, network listener, or remote access enabled through MCP.
- `mock` provider works without any model usage. Antigravity headless `agy -p ... --output-format json --sandbox` is an opt-in adapter and is **not tested on the user's actual Windows host**. A Windows `.cmd`/`.bat` launcher is rejected pending a Windows-specific safe argument transport.
- `codex-app` is a deliberately non-executing provider slot. Codex App Server integration requires a separate OAuth/client and event/approval test, not use of reverse-engineered web endpoints.
- NVIDIA GPU diagnostic is available through `nvidia-smi` if present. GPU inference, persistent supervisor, local LLM model routing, BPR40 publication, Chrome bridge, and real Codex app-server execution are **not yet implemented**.
- No billable API provider or automatic fallback. This package does not register/login via OAuth or ask for account tokens.

## PowerShell smoke test (isolated TEMP workspace)

From the extracted repository root in PowerShell:

1. `Set-ExecutionPolicy -Scope Process Bypass -Force` (only if needed and allowed by your security policy).
2. `./scripts/run-tests.ps1`
3. `./scripts/demo.ps1`

The demo creates a **new** temporary test database under `%TEMP%`, submits a mock task, completes it, and reports the current status. It never edits `CODEX_HOME`, BPR40, `.codex`, `AGENTS.md`, Windows registry, or browser state.

Alternatively set `PYTHONPATH` to the package `src` directory, then use the standard module command. The CLI always requires `--db <dedicated-local-path>`. Only `init` creates a new database:

- `python -m rai_fabric --db <isolated-state.db> init`
- `python -m rai_fabric --db <isolated-state.db> submit --workspace <your-test-repository> --provider mock --objective "test task"`
- `python -m rai_fabric --db <isolated-state.db> run-once --provider mock`
- `python -m rai_fabric --db <isolated-state.db> tasks`
- `python -m rai_fabric --db <isolated-state.db> mcp --workspace <your-test-repository>`

Manual worker operations (`checkpoint`, `heartbeat`, `finish`, `confirm-cancel`) require an active lease token in the `RAI_LEASE_TOKEN` environment variable. This is safer than putting a credential in a command-line argument. Do not log or disclose claim outputs because `claim` returns a lease token to the local operator.

## MCP clients

Register an stdio MCP server with Python executable and arguments:

- `-m`, `rai_fabric`, `--db`, `<isolated-state.db>`, `mcp`, `--workspace`, `<explicitly-allowed-test-repository>`.
- Set `PYTHONPATH` to the extracted repository's `src` directory, or install the package in an isolated venv and use its interpreter.
- Use a client that supports the 2025-11-25 MCP handshake, not a mandatory 2026-only MCP implementation.

Eight read-only tools:

| Tool | Function |
|---|---|
| `rai_health` | Service identity and mode |
| `rai_tasks_list` | Task metadata without lease credentials |
| `rai_task_get` | Task + current checkpoint |
| `rai_checkpoint_latest` | Checkpoint with recomputed SHA-256 |
| `rai_workspace_list` | Bounded directory listing, denylisted secrets |
| `rai_workspace_read` | Bounded UTF-8 read (max 32 KiB) |
| `rai_git_status` | Git tracked-file status |
| `rai_gpu_status` | NVIDIA diagnostics via nvidia-smi |

Do not expose this read-only stdio server to untrusted remote users yet: file names, task objective texts and Git status can still be confidential. It is designed for a local trusted client inside an explicitly selected workspace. There is no authentication, network gateway, audit policy, or adversarial multi-user filesystem defense.

## Checkpoint semantics

Every task transition includes an event. Submission, dispatch, worker result, cancellation, expired-lease recovery, and explicit requeue also create a structured checkpoint. Each checkpoint records `{task_id, timestamp, stage, verdict, cursor, evidence}` plus SHA-256; the latest checkpoint is verified on read. SHA-256 **detects accidental alterations**, but is not a tamperproof signature. A PASS worker result certifies that the *executor stage completed*, not that an independent code review was performed.

`recover` marks expired RUNNING work as BLOCKED / `VERIFY_EXTERNAL_SIDE_EFFECTS`. The operator must verify side effects and explicitly run `requeue --acknowledge ...` to retry. External agents are never restarted blindly.

## Evidence and future stages

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/ROADMAP.md`](docs/ROADMAP.md), and the bundled test suite. Testing has been performed in an isolated Linux environment with Python 3.13. Native Windows and real provider integration remain pending acceptance tests. All generated package files have a manifest with SHA-256 hashes.

## Donor references

The **ideas**, not source code, were informed by:
- https://github.com/Yeachan-Heo/oh-my-codex (MIT, Yeachan Heo)
- https://github.com/obra/superpowers (MIT, Jesse Vincent)

Independent design and implementation; no dependency on the donor repositories. BPR40/DUTY remains an external, read-only authority until an explicitly approved bridge is validated.
