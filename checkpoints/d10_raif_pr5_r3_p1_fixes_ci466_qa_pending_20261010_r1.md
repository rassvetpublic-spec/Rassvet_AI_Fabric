# RAiF PR #5 — R3 after independent QA

Date: 2026-10-10. Project-owned checkpoint on AG_pather; does not authorize merge.

## Independent R2 QA

Original [QA review](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/5#pullrequestreview-5480276024) = `QA_BLOCKED / 3 P1`: unbounded Git PIPE capture, untrusted PATH executable, effect-state downgrade at higher checkpoint generation.

## Corrective R3

- Candidate HEAD: `112cff5fae434dce3384b8d484ecf33a70ed20cb`, tree `d18587bdba2b0850bdb2962926b646730e792ffa`.
- P1-01: concurrent bounded 32-KiB-per-stream subprocess capture and owned process kill/reap.
- P1-02: Windows PATH fallback removed; pinned `C:\Program Files\Git\cmd\git.exe` requires SHA-256 `78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f`.
- P1-03: reject transitions away from previously non-NONE external effect; no laundering blocked states into NONE.

## Exact Windows CI

[CI #38076414820](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38076414820): `SUCCESS` 466/466, Windows preflight, SQLite mock and Codex-mock PASS; new hostile 4-MiB output, child timeout, fake PATH/hash and effect-downgrade tests are present in the job logs.

## Remaining gates

R3 [independent delta-QA request](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/5#issuecomment-6100886371) is posted; the two old inline P1 threads remain open. New host R3 QA has NOT run. CI PASS does not attest powerloss durability, external effect ledger or independent QA.

PR #5 stays OPEN/DRAFT; `main@8dc6ee32...` unchanged. Do not touch `C:\GIT\Rassvet_AI_Fabric` (last observed 134 modified tracked files), merge AG_pather wholesale, or change G2/Tower.

**Cursor:** `RAIF/10.4-PR5_R3_INDEPENDENT_DELTA_QA`; after independent PASS, require owner MTD on exact PR #5 SHA before merge.
