# W2 / 10.5 — foreground synthetic worker (candidate)

**Scope:** synthetic-only, Windows-only, foreground-once; no background service, no live provider, no arbitrary executable, no implicit migration or automatic replay.

## Contract

1. A fresh isolated `FabricStore` uses explicit `EffectLedger.install_on_empty_store`, while the separate `SyntheticSQLiteTarget` must be a different verified SQLite file. Legacy schema v1 is never migrated automatically.
2. The worker claims **only `mock`**, records `PREPARED`, atomically commits `MAY_HAVE_RUN` before starting an allowlisted synthetic owned Windows Job (`EXIT_ZERO`, `EXIT_NONZERO`, `HANG_PARENT`, `SPAWN_DESCENDANT`). It never accepts a command, account, prompt or path to an executable.
3. A bounded cancellation callback reads `cancel_requested` and validates status, owner, epoch and lease deadline while the owned Job is active. On cancel, only the owned Job is terminated, `ActiveProcesses=0` is checked, then the current lease owner confirms cancellation.
4. On timeout, nonzero, missing Job evidence, or error, the task becomes `BLOCKED`, and any potentially-dispatched effect becomes `UNKNOWN_OUTCOME`. A missing synthetic target row after dispatch is never proof of no effect.
5. A successful child process is **not** proof of a target effect. Only an independent synthetic SQLite target commit and readback, with immutable matching receipt, can lead to `APPLIED_VERIFIED` and task `COMPLETE`.
6. After crash/restart, `recover_foreground_synthetic` performs only `store.recover()` plus ledger recovery, never executes child commands and never requeues any task with registered effect. Reconciliation is a separate action.
7. Only fixed category evidence is emitted. No lease tokens, raw payload, prompt text, credentials, foreign PIDs or target database contents appear in the public result.

## QA / evidence boundaries

- Unit tests exercise success, nonzero, timeout, cancellation, stale lease, invalid parameters, fake Job evidence, ACK loss after target commit, unreplayed recovery, and schema/provider denial.
- GitHub Windows CI uses the repository's preexisting workflow: full unittest discovery plus original SQLite mock and Codex-mock. No new cloud model calls.
- The Windows-specific tests must exercise actual owned Job cancellation (including descendants) and cancellation requested from a separate SQLite connection.
- **Not attested:** physical power loss, durable NTFS flush across hardware reset, Windows process breakaway escapes, real provider effect idempotency, cryptographic trust of an interpreter, or production supervisor.
- This is a feature candidate; a green CI run does **not** authorize release, merge, account switching, live inference, or changes to Tower/CKS/BPR40 authority.

**Cursor:** `RAIF/10_5_FOREGROUND_SYNTHETIC_WINDOWS_CI_AND_INDEPENDENT_QA`.
