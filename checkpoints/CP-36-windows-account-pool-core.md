# CP-36 — Windows Account Pool / offline quota-aware candidate planner

Date: 2026-10-10
Branch: AG_pather
Source commit: a80af69268e4907f034614bb142738c68d83611c

## Code created
- `src/raif_ag_supervisor/pool.py` — new dependency-free quota-aware planner.
- `tests/test_pool.py` — synthetic tests; no OAuth, no requests, no Antigravity process or Credential Manager writes.
- Groups: `gemini`, `claude_gpt`. Each candidate requires fresh known positive quota in BOTH 5-hour and weekly windows.
- Candidate score: largest of the minimum remaining fractions across both windows. Equal scores preserve registry order.
- A plan can be created only after a trusted HTTP 429 report on the source account and selected model group. 401/403 block; missing credential, unknown/stale/zero quota, disabled candidates, cooldown and vault errors all fail closed.
- A scheduled reset is NOT evidence of actual replenishment. A new verified snapshot is needed.
- `HandoffPlan` protects account handles from repr/safe_summary. `safe_summary` never includes account names, email or secret material.
- Purely proposes a target; does NOT mutate live credentials, auto-open browsers, patch binaries, restart processes, or claim continuous streaming.

## CI evidence
- Workflow: standard `windows-latest` runner, public repository, Python 3.12, one Windows job.
- GitHub Actions run: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38013658508 — conclusion: success; job duration ~22 seconds.
- No Linux runner was used. No real user data was uploaded to GitHub.
- Only one regular code batch committed to trigger this CI run. Documentation-only commits do not trigger CI.

## Current limitations
- Data source for actual provider quota readings is not integrated. Today the planner accepts ONLY externally provided validated quota snapshots.
- The existing Windows vault supports put/has/delete but intentionally no secret-reading or native Antigravity credential mutation.
- The successful CP-31 binary patch and CP-35 restart are independent of the pool; no actual account switching has yet occurred.
- No live-session handoff or in-flight stream replay. OAuth refresh and server eligibility remain outside CP-36.
- User's nine-account JSON is NOT included in GitHub or CI.

## Cursor
AG_pather / CP-36 CORE_AND_TESTS_PASS → CP-37 READ_ONLY_QUOTA_SNAPSHOT_ADAPTER → CP-38 LOCAL_WINDOWS_POOL_SMOKE_PACKAGE → CP-39 STANDALONE_SWITCH_PROBE.
