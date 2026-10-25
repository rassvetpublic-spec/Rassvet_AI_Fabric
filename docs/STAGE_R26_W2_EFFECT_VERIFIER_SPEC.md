# STAGE R26 / W2 — Security Repair R3 (shadow-only)

**Scope:** six-file, stacked candidate over RAIF PR #27 exact base `3f172c677d97f4d72c1e6fc1d871b93fdd706341`. This document is *not* an MTD, host grant, merge instruction or production admission. Fleet remains `HARD_PAUSED`.

## Goal lock

Preserve existing FastLab L3 and the pure, non-wired PR #26 `effect_receipt_contract.py` without introducing a second Router, execution queue or authority. Reject synthetic target success as proof of a real effect. Never mutate `main` or a production `tasks.db` from this candidate.

## Remediation after 2026-10-25 security review

Original 62/62 Windows tests were successful within the historical scope of PR #27 but missed six adverse scenarios. Original red tests and defects: [RAIF #21](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/21#issuecomment-6391724765); [Drive security evidence](https://drive.google.com/file/d/195k3tnbusQrfVCflOCBivB6t0B0v6Z_l/view?usp=drivesdk).

### 1. `trusted_target_verifier.py`

- No string-prefix containment. `operation_id` must be strictly relative, non-empty, without `..`, Windows paths, alternate data streams or embedded NUL.
- Root and each child component are inspected for symlinks/reparse points. Resolved target must be component-contained (`Path.relative_to`), a single-link file and at most 16 MiB. Stat/open/read/stat checks reject basic inode swaps. No claim of a fully race-free Windows host read under an actively malicious filesystem; the verifier is not production authority.
- Independently derive `target_revision = "sha256:" + actual_content_sha256`, never echo a revision supplied in a receipt. Missing, stale or forged revision fails closed.
- Synthetic sinks are test fixtures only and never yield host `VerifiedReadback` from the production class.
- In-memory grant registration is NOT a signed MTD. Unverified registries fail closed by default; test fixture supplies an explicit offline-only callback. Any production issuer authentication needs a separate owner-approved host channel and gate.

### 2. `w2_effect_bridge.py`

- `register_real_intent()` is an opt-in **shadow-only** staging API for disposable tests, and cannot claim or run a real-provider task.
- `commit_verified_effect_receipt()` validates pure receipt admission and compares *all* persisted intent/operation fields, tasks status/cancellation, lease owner/token/hash, epoch and expiry inside a transaction.
- **Unconditional final fail-closed gate** `HOST_EFFECT_AUTHORITY_NOT_IMPLEMENTED`: even an otherwise matching lease plus source readback is not an authenticated execution/commit grant. It must not write `tasks.COMPLETE`, `result_json PASS`, `effect_operations APPLIED_VERIFIED`, `effect_receipts`, or a `PASS` checkpoint. This consciously removes the old synthetic positive completion test, replacing it with admissible-only evidence assertions.
- Production `FabricStore.claim()` restriction remains unchanged. Future live execution is a *separate* reviewed API with actual host authorization, durable effect reconciliation and CAS, not an in-place relaxation of this shadow candidate.

### 3. `w2_migration.py`

- Preserve transactional, idempotent v1→v2 on disposable DB, and fail closed on unknown version.
- Compare exact normalized `sqlite_master` definitions for all three tables, two explicit indices and both receipt immutability triggers. Reject modified/missing foreign keys, constraints, column layout or trigger bodies. Check `PRAGMA foreign_key_check`.
- DDL failure is converted to `FabricError`, with rollback of newly created schema and `meta.schema_version`. A corrupt v2 must NOT return successful NOOP.
- This is **not** permission to migrate any live SQLite DB. Backup/recovery/host-owner admission remains outstanding.

## QA and release gates

- The original six negative RED must become GREEN, alongside additional path, issuer, lease, intent, immutable-schema and rollback tests.
- Local smoke on a **temporary test mirror** is not exact-head native Windows proof. Retest the changed candidate with the **actual** `FabricStore` on isolated Windows checkout and record exit status, total collected tests, exact SHA, receipt and independent Drive ZIP readback. The historical 62/62 result is not transferable to a new HEAD.
- No paid GitHub Actions, daemon `QAWorkerService.run_cycle`, realtime provider, MCP activation, live LAN, main/CORE/Router/authority/host-policy change, merge or Fleet unpause.
- AX / PR #25 remains ready for *separate* exact-SHA owner MTD; AY / PR #26 remains pure `NOT_WIRED`. This W2 repair must not silently merge either source batch. New stacked PR is Draft.

**Status:** `SOURCE_PATCH_SECURITY_CANDIDATE / SHADOW_ONLY / NATIVE_WINDOWS_QA_PENDING / NO_PRODUCTION_PASS`.

**Next cursor:** `BLOCK_C_NEGATIVE_GREEN_ON_REAL_STORE__EXACT_HEAD_WINDOWS_RUNNER__TRUSTED_HOST_AUTHORITY_SEPARATE_GATE`.
