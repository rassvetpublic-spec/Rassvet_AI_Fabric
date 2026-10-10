# CP-38 — Windows local account preview, opt-in import, status, recovery

Date: 2026-10-10
Branch: AG_pather
Source commit: e60c3ff0b6f812e83f827b82c9c4b3a9427f52b3

## Implemented
- `src/raif_ag_supervisor/accounts_cli.py` exposes four local operations under `python -m raif_ag_supervisor accounts`:
  - `preview --file PATH`: validates input structure; counts accounts without writing credentials.
  - `import --file PATH --confirm-local-storage`: explicit consent is required before storing account refresh tokens through the existing WindowsCredentialVault + LocalAccountRegistry. No automatic OAuth requests or native Antigravity credential replacement.
  - `status`: counts RAiF registry and Credential Manager entries; only aggregate numbers are output.
  - `recover --confirm-recovery`: explicit consent for recovery of the existing write-ahead journal; no secrets displayed.
- The root CLI `src/raif_ag_supervisor/__main__.py` dispatches `accounts` and supports `pool-demo` (synthetic only), retaining original `status`.
- Output contains only counts and fixed status strings. Input paths, account emails, opaque handles and token values are not displayed. Import reads at most 1 MiB into memory; source JSON is never copied into Git or runtime outputs.
- Accounts remain isolated under `RAiF_AG_Supervisor:account:<opaque-id>`. The live `gemini:antigravity` record and Language Server are not modified.
- `tests/test_accounts_cli.py`: synthetic preview, confirmation, import, recovery, redaction, negative cases.

## CI
- GitHub Actions Windows-only run: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38013919355
- Result: success, standard `windows-latest`, public repository; no Linux, no real tokens and no provider request.
- Code is not yet tested on RASSVET_DESKTOP; user has not executed live import.

## Limitations
- Imported refresh tokens are saved as isolated credentials but cannot yet authorize or hot-switch the real Antigravity Standalone session.
- No actual provider quota HTTP client or verified account identity / session attestation.
- Import is not a replacement for the already successful CP-31 local patch; do not change the installed Language Server again.
- The previously uploaded user JSON is sensitive, is NOT included in source, tests, CI or a public checkpoint; use it only locally with explicit permission and consider rotating previously exposed refresh tokens.
- The current CLI is a developer interface, not yet the promised two-file Windows ZIP + PS1 user package.

## CURSOR
AG_pather / CP-38 WINDOWS_CLI_TESTS_PASS → CP-39 BUILD_SELF_CONTAINED_WINDOWS_ZIP_PS1 → CP-40 LOCAL_VAULT_PREVIEW_AND_RUNTIME_VALIDATION → CP-41 LIVE_SESSION_SWITCH_RESEARCH.
