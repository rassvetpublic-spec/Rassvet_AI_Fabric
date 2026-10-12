# W2 F2.1 R2 — Windows CI 521 PASS, independent QA and host F2.2 pending

12 October 2026. Exact [DRAFT PR #8](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8): `4c4dff1433d5b1ccd11c3a6fe45348b4ec7a9395`, tree `9535e1c44291d994a6d6f998c0f13ea1705749b7`, parent `c42a905f904b36c8823930caaedf90951b603651` (merged Level-4 and follow-up docs).

## Verified new Windows CI

[GitHub Actions #38187611702](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38187611702) on R2 exact SHA: `SUCCESS`, `Ran 521 tests in 52.693s`, `OK`; Windows preflight, SQLite mock and Codex-mock PASS. Five new hostile tests: direct claim bypass, synthetic effect API for real provider, APPLIED phase without receipt, wrong receipt checksum, and Job Object Assign failure cleanup — all individually `ok`.

## Source QA status

Original R1 [QA request](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8#issuecomment-6115408037) has no completed verdict. Updated R2 [exact-source independent QA request](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8#issuecomment-6115552984) is posted. **PENDING**, not an independent QA PASS. Author source self-audit identified two source-level contract bypasses and applied corrections; no cryptographic external attestation is claimed.

## Owner host F2.2 handoff

Prepared standalone `RAiF_W2_F2_2_HOST_QA_R1.zip` (4847 bytes, SHA-256 `c466a7fb68a066076417a02f57475f5da5d35a002aab931ae9ffee57d8cd63c0`). It pins the commit+Git tree, runs one disposable D: checkout + full Windows unittest + mock and Codex-mock, emits local RESULT ZIP for owner review. **NOT RUN on Windows owner host**; no automatic upload. Local C:\GIT WIP untouched.

## Persistent limitations

Real provider adapter and remote target attestation remain disabled. No physical power-loss proof or real Windows worker Job Object guarantee. Source QA, host QA, and exact SHA owner MTD needed before merge PR8. Main not modified by this flow; AG_pather carries docs only.

**Cursor:** `RAIF/W2_F2_1_R2_INDEPENDENT_QA_AND_F2_2_OWNER_HOST`.
