# Architecture Decision Record — RAI Fabric R0.1

Date: 2026-10-10. Status: TESTED CORE / UNVERIFIED PROVIDERS.

## Decision

Create an original Windows-first orchestration system rather than modifying `oh-my-codex`, `Superpowers`, `omx-app`, `.codex`, or BPR40 runtime.

The **core** is a local, deterministic task/event store. The **MCP gateway** is intentionally read-only. **Provider drivers** have explicit opt-in and sandbox defaults. **BPR40 authority** is external and cannot be superseded by this software. **ChatGPT web** and private backend endpoints are not used for agent dispatch.

## Component boundaries

```text
BPR40 / DUTY authority (external, currently NO WRITE BRIDGE)
             |
      Future BPR40 adapter (schema/readback/provenance)
             |
     RAI CORE (SQLite/WAL + checkpoint + event journal)
       |          |                  |
     CLI      MCP stdio           Worker driver
     local    read only      mock | agy (opt-in) | codex (blocked)
       |          |                  |
   operator  files/git/GPU         subscribed clients (future verified)
```

## Defined contracts

- A task has a stable `id`, `objective`, `provider`, `workspace`, dependencies and state.
- Terminal: `COMPLETE`, `FAILED`, `BLOCKED`, `CANCELLED`.
- A live lease is (task_id, owner, token SHA-256, epoch, deadline). Leases are scoped to RUNNING.
- Only the lease holder can add progress or finish. `lease_epoch` fences stale workers even when a retry is allowed.
- Each checkpoint has stage, PASS/PARTIAL/BLOCKED verdict, cursor, evidence, SHA-256 and ordered sequence.
- Every event records task, kind, timestamp, data. No authorization token is included in a journal entry.
- Dependencies of a queued task must all be `COMPLETE` before claim.
- Expiration is reconciled, never automatically replayed. Fail-closed is required when side effects are uncertain.
- `PASS` at the worker stage is not BPR40 authority. Review/independent acceptance must be separate later.

## Basic threat model

Assets: local source code, Windows credentials, ChatGPT/Google subscription sessions, BPR40 authority, GPU resources, user files.
Threats: agent prompt injection, malicious repository symlinks, accidental credential exposure, duplicated side effects from lost workers, provider charge fallback, unauthorized shell access.
Controls in R0.1: no network listener, stdio-only MCP, read-only tools, specific workspace, symlink/junction rejection, blocked sensitive paths, no arbitrary shell, 32-KiB file ceiling, no API-key providers, local explicit CLI mutations, non-replay after crashes.
Not yet mitigated: multi-user filesystem race/TOCTOU, distributed authentication, signed evidence, stronger Windows job-object process-tree termination, remote tunneling, BPR40 publish policy. **Do not expose MCP outside trusted local context.**

## Build and verification

Runtime dependency count: zero (standard library). Test runner: `unittest`. Native Windows smoke and subscription inference require interactive, explicitly authorized verification. `scripts/demo.ps1` is an isolated mock end-to-end exercise.
