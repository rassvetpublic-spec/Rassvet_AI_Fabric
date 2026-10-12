# RAiF W2 F2.1 R2 — current main integration and adversarial guard

Date: 2026-10-12. Candidate PR #8, still **DRAFT**, no merge permission.

## Source parents

- W2 predecessor: `b36cfbc0850b5f49327162133a2a4840ba82e1ee`, old main 34e5f836..., Windows [CI #38186544803](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38186544803) = **514/514 PASS**.
- Main Level-4 code passed as `8513979110676f7a72faeefa3a1c393867946858` through merged PR #9; Windows [CI #38186830397](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38186830397) = **483/483 PASS**. Current `main@c42a905f904b36c8823930caaedf90951b603651` adds only documentation checkpoints, no executable change since that CI.
- The four Level-4 changed files do not overlap 13 original W2 files; use two-parent merge commit preserving both histories and all exact blobs.

## Self-audit P1 candidates from code inspection

1. `FabricStore.claim()` could claim real `antigravity` tasks on schema v2 if bypassing `worker.run_one` gate. Fix: reject explicit external provider and exclude them when unfiltered.
2. `FabricStore.finish(PASS)` previously accepted phase `APPLIED_VERIFIED` even with no effect receipt. Fix: for every ledger operation, require receipt, correct payload/verdict and canonical evidence SHA-256. Check within same SQLite transaction.
3. Synthetic `EffectLedger.prepare_effect/mark_possible_dispatch` now double-check provider type `mock/codex-mock` even with invalid admin-injected active lease.
4. Windows-only fault injection exercises failure of `AssignProcessToJobObject`: suspended child must never `ResumeThread`, must be terminated by its own HANDLE.

These counterexamples are **author self-review**, not an independent QA verdict. New negative tests are written but their status is **NOT_RUN until exact SHA Windows CI**. Existing 514/514 and 483/483 do not validate combined candidate.

## Safety and next gates

Only test SQLite sink and allowlisted synthetic subprocesses. No user-host C: mutation (last observed 134 tracked WIP), no real providers, no Tower/Router/CKS/G2 changes. No physical power-loss, remote idempotency or live account attestation. Future host acceptance in isolated D: only. PR #8 DRAFT until independent QA, F2.2 host readback and explicit owner MTD for exact commit.

**NEXT:** `RAIF/W2_F2_1_R2_MERGED_SOURCE_WINDOWS_CI_THEN_QA`.
