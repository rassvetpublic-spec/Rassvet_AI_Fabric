# CP-46 — Windows-only local credential vault package (PowerShell 7)

Date: 2026-10-10. Branch: AG_pather.
Source: CP-45 successful schema check (9 accounts, no prior RAiF vault entries).

## Artifacts (delivered as chat attachments; NOT committed to public GitHub)
- RAiF_AG_CP46_LocalVault.zip
  SHA-256 A3A97FCE818E21503B6544D9B765B74F8222D6C903077A11B5002A53E19FC581
  Contains Import-RAiFAccounts.ps1 and README.txt. ZIP CRC passed.
- RAiF_AG_CP46_Run.ps1
  SHA-256 89B1D2B46C89D59A4B21EFE1AF3607276954F347875A14F6863048B25E2044E8
  Launcher pinned to source archive hash.

## User's Windows deployment contract
- Place exactly the ZIP and PS1 in D:\ЗАГРУЗКИ; keep antigravity_accounts_2026-09-15.json there.
- Project root: C:\GIT\Rassvet_AI_Fabric.
- Temp: C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP46_<run-id>.
- Final sanitized result: C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP46_RESULT_<run-id>.zip.
- PowerShell 7 only, using pwsh.exe -NoProfile -ExecutionPolicy Bypass; policy is not changed globally.
- Explicit import command:
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP46_Run.ps1" -Mode Import -ConfirmImport
- Default mode is Preview (no credential modifications); -Mode Import without -ConfirmImport fails safely.
- Other modes: Status and Recover; Recover requires -ConfirmRecovery.
- Launcher finds ZIP next to PS1, verifies expected SHA-256, unpacks then invokes payload without a Python dependency.

## Native local import design
- All sensitive JSON parsing happens on the user's PC, in process memory only. Fields must be exactly email and refresh_token; duplicate emails, malformed types, oversized data and invalid counts fail closed.
- Uses native Windows CredWriteW/CredReadW/CredDeleteW via managed P/Invoke. Writes new GENERIC credentials only to RAiF_AG_Supervisor:account:raif-<random-opaque-id>.
- Does not modify the native gemini:antigravity target, its credential values, SQLite state or the running Language Server/Antigravity application.
- Registry at %LOCALAPPDATA%\RAiF\AGSupervisor\accounts.json holds only opaque handles, no email or token. Existing nonempty registry blocks accidental duplicate import.
- Staged import writes pending-import.json with handles before native writes; after a successful commit it removes the journal. Failures attempt rollback. Recover distinguishes committed vs orphaned stages, never removes committed accounts.
- Exclusive Windows file handle blocks simultaneous writers. Some crash/disk failure modes may require manual recovery; this is not a production OAuth security audit.
- All stages recorded in STEPS.jsonl with UTC, stage name, state, safe error code, elapsed time. Per-account stages use numeric index only.
- Result ZIP strict allowlist of RECEIPT.json, STATUS.txt, SUMMARY.txt, STEPS.jsonl, report.json; no email, token, source JSON, binaries or SQLite database.

## Risk and validation limits
- Static verification only: ZIP CRC, source integrity, SHA pin, safe target namespace, no provider requests and no native Antigravity credential writes by source inspection.
- PowerShell payload has not yet been executed on RASSVET_DESKTOP or in GitHub Windows CI. It may require corrections based on a redacted RESULT ZIP; success must not be assumed before that.
- Refresh tokens uploaded in earlier conversations are sensitive; recommend obtaining fresh tokens after secure local migration. Never upload the original JSON as a diagnostic artifact.
- Credentials in RAiF Vault are not yet usable to hot-swap the running Antigravity Standalone process. Import is for isolated storage, not an OAuth validity test or quota bypass.
- No backup of the patched language_server.exe is created. The CP-31 patch is not re-applied.

## Cursor
AG_pather / CP-45 SCHEMA_VALIDATED → CP-46 LOCAL_IMPORT_PACKAGE_PREPARED (NO_EXECUTION) → CP-47 USER_RESULT_ZIP → CP-48 RUNTIME_VAULT_AND_SWITCH_VALIDATION.
