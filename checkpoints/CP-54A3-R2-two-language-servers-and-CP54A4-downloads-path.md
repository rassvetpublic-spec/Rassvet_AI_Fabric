# CP-54A3 R2 readback: TWO language_server processes; CP-54A4 new Downloads-only package

Date: 2026-10-10. Branch: AG_pather. Status: CP54A3_R2_DIAGNOSTIC_SUCCESS / RPC_NOT_TESTED / CP54A4_STATIC_PACKAGE_READY.

## User's new Windows placement contract
- `C:\GIT\Rassvet_AI_Fabric` is now a real Git checkout according to the user's current report. This specific fact is USER_REPORTED, not yet independently read back on their host.
- All new CP54A4 runtime directories and RESULT ZIP files are direct children of `D:\ЗАГРУЗКИ`. Do NOT write staging, exported logs, or RESULT ZIP inside the Git checkout.
- Each CP54A4 runtime folder: `D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_RUNTIME_<runid>\`.
- Result: `D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_RESULT_<runid>.zip`. Source ZIP + launcher are saved in `D:\ЗАГРУЗКИ`.
- Launcher checks for a `.git` marker in the project as read-only evidence, and rejects a DownloadsRoot nested under project root.

## Uploaded CP54A3 R2 result
- Filename: `RAiF_AG_CP54A3_RESULT_20261010_085407_0b602753.zip`. SHA-256 `ca8b84506369517f34fc6f840cea41a1a8f90e92b66b357b75f70f8cf4b2ffe7`.
- ZIP CRC PASS; exact allowlist `STATUS.txt`, `SUMMARY.txt`, `RECEIPT.json`, `STEPS.jsonl`, `report.json`.
- Status SUCCESS, probe_exit_code=0, source_zip_sha256_verified=true, PowerShell 7. All **44** STEPS events present, 0 warnings and 0 failures.
- `report.process.language_server_count=2`; there is **no unique process** to query. `report.discovery.verdict=NO_UNIQUE_LANGUAGE_SERVER`.
- The old single-PID probe intentionally skipped CSRF extraction, TCP-port discovery, and actual RPC requests when more than one Language Server was running.
- `csrf_argument_found=false`, listener counts 0, and RPC statuses SKIPPED mean **NOT TESTED** in this run, not that credentials, ports or RPC were absent.
- No native credential change, no RAiF Vault access, no process mutation, no direct external provider requests, no returned secret values; identity/hotswap unverified.

## CP54A4 implementation (new downloadable conversation-only bundle)
- Existing static single-PID probe was expanded to independently inspect **up to 4** language_server.exe instances, with each PID and exact StartTimeUtc marker. No arbitrary first-PID selection or merging of CSRF/ports across instances.
- Per-instance metadata: PID/start time, safely classified parent role, commandline/CSRF presence **as booleans only**, three independent IPv4 ownership inventories (`GetExtendedTcpTable`, `Get-NetTCPConnection`, `netstat.exe`) and passive IPv6 cmdlet inventory.
- Only if a known PID owns its IPv4 loopback/wildcard listener, and that same instance has its own CSRF argument, an identity-preserving recheck allows `HasAuthToken`, then `GetAuthStatus`. Connect v1, fixed localhost URL and method allowlist, 2s timeout, no redirects, no proxy, 16KiB response bound.
- The native CSRF and full command line remain in memory on the user's computer; never written to GitHub, JSON report or RESULT ZIP. `hasValidAuth` from the previously patched LS is UNTRUSTED as independent account evidence.
- Source ZIP `RAiF_AG_CP54A4_MultiInstanceTransport.zip`, 6995 bytes, SHA-256 `A0ED0009659C91D0843B1A465E2CF3F37759607278D9CE2573CF919F302B8DB7`; contains exactly `probe.ps1`, `README.txt`; CRC PASS.
- Launcher `RAiF_AG_CP54A4_Run.ps1`, 11139 bytes, SHA-256 `3D0D9D622DF1954A79DF7FA9F400E73814657774AD08D2590E43D04A99223C3C` (PowerShell 7 source UTF-8).
- No AG-tools, no Python on user's PC, no imported account JSON, no Credential Manager writes/deletes, no process restart/stop, no OAuth refresh, no mutation of checkout.
- Source ZIP, launcher and all RESULT details remain off public GitHub. This checkpoint contains only aggregate nonsecret facts and hashes.

## Static QA
- Python static suite PASS: confirms previous R2 report content and 44 events, source ZIP CRC and two-entry allowlist, launcher source ZIP hash, correct file glob, exact report schema fields, safe process loop (up to 4), separate CSRF resetting per process, strict localhost port ownership, no credential/process writes, no old output paths.
- Basic lexical delimiter checks for both PowerShell sources PASS (NOT equivalent to PowerShell AST or runtime execution).
- Actual PowerShell 7 run not executed in analysis container. Host Windows result required.

## User command (both files saved to D:\ЗАГРУЗКИ)
`pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_Run.ps1"`

## Branch / policy
- `AG_pather` prior HEAD `8a7ac63c81cf073d55312a15496b2768678087ce`. No pushes to main, no changes to CONTROL_TOWER, BPR40 Router or provider credentials, no new CI trigger (documentation-only commit).
- Fabric Core parallel cursor remains `RAI-FABRIC / 10.1B-WINDOWS_HOST_ACCEPTANCE` and detached merge rehearsal follows verified host QA, not this CP54A4 probe.

## Cursor
`AG_pather → CP-54A4 / MULTI_LS_DOWNLOADS_ONLY_RECEIVE_RESULT → CHECK_RPC_TRANSPORT_AND_INSTANCE_ROLE → G1 / SUPPORTED_READONLY_NATIVE_INTERFACE_OR_INCONCLUSIVE`.