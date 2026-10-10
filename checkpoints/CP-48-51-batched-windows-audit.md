# CP-48–51 — Windows read-only batch package

Date: 2026-10-10. Branch: AG_pather.
Status: PACKAGE_CREATED; Windows runtime not yet tested.

## Updated evidence
User confirms all nine accounts from their existing local manifest are usable in AG-tools. This is USER_ATTESTED evidence of AG-tools functionality, not independent proof of validity for Antigravity Standalone live sessions.

## Packaged deliverables (ChatGPT attachments only)
- `RAiF_AG_CP48_51_WinAudit.zip`: SHA-256 `82F519362B4F753B011BCB1F5723477B1A3D59FA815B6BE30DD7C82221D95FE5`.
- `RAiF_AG_CP48_51_Run.ps1`: SHA-256 `9C4112BBF6DC80661A6B0D11AFE96FB77D72CCD0821437B02BF63F4E8ED21C51`.
- Both files placed in `D:\ЗАГРУЗКИ`; run via `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP48_51_Run.ps1"`.
- Output: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP48_51_RESULT_<run-id>.zip`.
- ZIP CRC verified, pinned SHA-256 present in the launcher. Read-only source scan passed. Full PowerShell 7 test on RASSVET_DESKTOP pending.

## Batch scope
1. **CP-48:** read only `%LOCALAPPDATA%\RAiF\AGSupervisor\accounts.json` metadata (9 opaque IDs expected), check matching Credential Manager *target presence* via `cmdkey.exe /list`, inspect pending journal. Never export target names/handles or blobs.
2. **CP-49:** record user attestation `USER_REPORTED_AGTOOLS_ONLY`, do NOT query OAuth or expose account identity.
3. **CP-50:** optional read-only local GET `127.0.0.1:19527/health` and `/accounts` (observed in AG-tools source module `src-tauri/src/modules/http_api.rs`, whose comment says it may not be active in the main application). If enabled, extract only counts of accounts and cached quota models; no raw payload in output. If unavailable, `INTERFACE_UNAVAILABLE` is expected and nonfatal. No POST/refresh/provider calls, redirects or HTTP proxy.
4. **CP-51:** read process counts/PID/start for Language Server and safe file hash comparison with successful CP-31; do not access process memory or change native `gemini:antigravity` credential.
5. Structured `STEPS.jsonl` with stage state/timestamp/elapsed/code, and allowlisted `report.json`, `RECEIPT.json`, `STATUS.txt`, `SUMMARY.txt`; final ZIP in project root.
6. Fail closed on invalid input/state; unknown cached quota is not construed as live quota and does not authorize a switch.

## Not included
- No import/reimport of nine user tokens, no OAuth refresh, no logout, no process restart, no binary patch, no real account rotation.
- CP-52 must be a separately authorized experiment with return-to-original-session validation; seamless continuation is not yet proven.
- No user manifest/token/email/SQLite/profile data committed to public GitHub, CI or included in source ZIP.

## Cursor
`AG_pather → CP-48_51 STATIC_PACKAGE_READY → CP-48_51 RECEIVE_RESULT_ZIP → CP-52 SWITCH_POC_DESIGN`.
