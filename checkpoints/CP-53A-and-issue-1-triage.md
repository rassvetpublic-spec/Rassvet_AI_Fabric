# Issue #1 / CP-53A — triage and Windows hardening

Date: 2026-10-10. Branch: AG_pather.
Issue: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/1

## Verified against code
- tests/test_windows_vault.py was added independently in main (rai_fabric.windows_vault DPAPI) and AG_pather (raif_ag_supervisor.windows_vault Credential Manager). Genuine add/add merge collision. Move AG version to tests/test_supervisor_windows_vault.py preserving content.
- tests/test_cli.py on AG_pather used encoding utf-8 without errors=replace for captured subprocess, matching the review's failure mode.
- scripts/demo.ps1 and scripts/run-tests.ps1 trusted presence of py/python, not their actual runnability. Shared resolver now probes Python >=3.11, handles WindowsApps aliases, and enables UTF-8 for child processes. Note: the issue's example with a silent 'import sys' inside the PowerShell if condition is not a reliable success check, so the resolver prints a controlled ready marker and checks LASTEXITCODE.
- Review's PID assertion needs qualification: src/raif_ag_supervisor/session_probe.py already implements kernel32.GetProcessTimes via windows_process_start_marker. src/raif_ag_supervisor/verification.py explicitly requires (PID, start_marker) and refuses an unproven unchanged PID. Process discovery records themselves only include PID; consumers must use the stronger verification gate.
- The issue also proposes a unified CLI, localhost proxy, and protocol recorder. These are architecture proposals, not existing validated functionality.

## Uploaded CP-53A diagnostic
- ZIP RAiF_AG_CP53A_RESULT_20261010_064117_3437ebfa.zip, sha256 4a311048c7da26b9d0764f53221cfe57124c53fbe5a81d4ae1fde47d970e122a. CRC OK.
- Read-only SUCCESS, 38 STEPS events, no failure. 1 AG-tools root found, 9 profile files parsed, disabled=0, parse_error=0, refresh_missing=0, access_missing=0, expiry_missing=0.
- expired_or_near_expiry=9, fresh=0. raif_vault_records=9; 8 AG-tools refresh tokens match a RAiF Vault entry, 0 fresh matches.
- Verdict REFRESH_ACCESS_CACHE_IN_AGTOOLS. This does not establish any invalid OAuth refresh token. Do not switch Standalone based on stale cache; do not assume the unmatched profile is revoked. No user credentials or paths were exported.
- Source data of users and zip results are not committed, only aggregated statistics.

## Decision
- Preserve existing main DPAPI tests on merge; distinguish supervisor tests by filename.
- Keep Windows Python runner compatible with AppExecutionAliases and locale without changing global system settings.
- Await Windows CI result for the changed test/launcher sources.
- CP-53B: refresh AG-tools access-token cache through supported AG-tools controls after current QA work finishes; then re-audit counts. Do not retry CP-53 Live with 0 fresh profiles. CP-54 actual switching remains separate and needs explicit user opt-in.

CURSOR: AG_pather / ISSUE_1_TEST_COLLISION_FIXED_PENDING_CI → CP-53B AGTOOLS_REFRESH_CACHE → CP-54 CONTROLLED_LIVE_SWITCH.

## Validation after code fix
- Code commit: `d88e764d6340993314f1d1012948601ee0e8a5ef`.
- Windows GitHub Actions: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38021738781 — status completed, conclusion SUCCESS (run #28).
- Conflict file was renamed at the Git tree level in one atomic commit, preserving its blob hash and test cases.
- Main branch has NOT been merged. Other potential merge conflicts and the actual PowerShell behavior on the user's local Windows are outside this CI result.
- Issue #1 remains open until broader review is completed; optional architecture RFCs are not implemented.
