# CP-39 — Windows offline preflight ZIP + PS1, root result path

Date: 2026-10-10
Branch: AG_pather
Purpose: verify local account manifest and Windows environment without importing any secrets.

## Packaged artifacts (delivered in ChatGPT, NOT stored as binary in GitHub)
1. `RAiF_AG_CP39_WinPreflight.zip`, SHA-256 `6675a59cbb349e3fc3d58c1bb9a47722233e5f33b2e153e69d53b499125db140`.
   Contains `probe.py` and `README.txt`. ZIP CRC passed.
2. `RAiF_AG_CP39_Run.ps1`, SHA-256 `5a3f391120565f0e05d6bf374b0d749f3b7844c3666d2057bdb1d3b7b1a35842`.
   Checks the ZIP hash before unpacking/running. Windows PowerShell 5.1-compatible launcher intended, but native Windows execution still requires user test.

## Transfer contract
- Download EXACTLY two files to `D:\ЗАГРУЗКИ`.
- Run: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP39_Run.ps1"`.
- Staging: `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP39_<run_id>`.
- Final sanitized ZIP goes DIRECTLY in the repository root: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP39_RESULT_<run_id>.zip`.
- `.gitignore` excludes such diagnostic ZIPs from ordinary commits; avoid force-add.

## Read-only checks
- Python availability, root directory/Git metadata presence, safe process names/PIDs for Antigravity / language_server / agy.
- Installed Language Server file presence/size/SHA-256, not binaries or memory dump.
- Credential Manager: only aggregate count/presence of known target names (cmdkey stdout discarded).
- If available in the download directory, `antigravity_accounts_2026-09-14.json` is read in memory ONLY to validate exact field schema, duplicates, value types and count (max 1 MiB); never copied or printed.
- RAiF registry: metadata presence and count, pending-recovery flag; no opaque handles.
- The resultant ZIP contains only `report.json`, `SUMMARY.txt`, `STATUS.txt`, `RECEIPT.json`. No tokens, email, SQLite or local files.
- Launcher reports sanitized known failure codes. It does not patch, restart, authenticate, change native Credential Manager state, run model queries, or send network requests.
- PowerShell execution-policy bypass is per process; no machine-wide policy change and no elevation.

## Tests and limitations
- Synthetic Linux-side test of `probe.py`: success, account count extracted, no synthetic secret in report; ZIP CRC and hash verified.
- The package has NOT yet run on RASSVET_DESKTOP. PowerShell syntax and Windows-specific calls remain to be validated there.
- CP-38 repository CLI with real opt-in local vault import separately passed GitHub Windows CI: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38013919355 .
- CP-39 itself only previews and diagnoses; it does NOT store real refresh tokens or switch live accounts.

## CURSOR
AG_pather / CP-39 PREVIEW_PACKAGE_CREATED → CP-40 USER_RESULT_ZIP → CP-41 SAFE_LOCAL_IMPORT_AND_LIVE_SESSION_VALIDATION.
