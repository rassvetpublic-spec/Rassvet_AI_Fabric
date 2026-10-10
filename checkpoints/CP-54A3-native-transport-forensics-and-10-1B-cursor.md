# CP-54A3 — read-only Windows TCP transport forensics; Fabric 10.1B hold

Date: 2026-10-10; branch AG_pather.
Status: PACKAGE_STATIC_QA_PASS / WINDOWS_RUNTIME_PENDING.

## Received input from last run
- Last user result: `RAiF_AG_CP54A2_RESULT_20261010_080335_19c8d912.zip`; SHA256 `268880022903ac54c0cbeeaa9ad76ccca9d06447a47737df863acfb9e17d3f0f`; CRC PASS.
- Receipt: SUCCESS/exit=0 only for running the read-only diagnostic. Language Server PID 19972; instance was stable during probe; CSRF argument was located in memory.
- `Get-NetTCPConnection -OwningProcess <PID> -State Listen -ErrorAction Stop` produced a step WARNING. Ports identified: 0; actual HTTP RPC requests: 0.
- Consequently, `RPC_NOT_TESTED` rather than `RPC_BROKEN`. No native account switch or process mutation.
- A zero-listener result does not rule out named-pipe/IPv6/private host-owned interfaces or an OS enumeration error.

## New CP-54A3 bundle
- `RAiF_AG_CP54A3_TransportForensics.zip`: SHA256 `6140814BF55BBFE70286FB4E2DE3021F1A37FE717472DCF378BF59BCC020EDFE`. Strict contents: `probe.ps1`, `README.txt`. ZIP CRC PASS.
- `RAiF_AG_CP54A3_Run.ps1`: SHA256 `0925D550FE231285650F36FE21A977B59ACBE9B30CB961CB64019E84993596D3`. ASCII-only, pinned ZIP hash, strict RESULT file allowlist.
- User delivery: two files in `D:\ЗАГРУЗКИ`; `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A3_Run.ps1"`.
- Final output directly at `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP54A3_RESULT_<runid>.zip`.
- Execution uses PowerShell 7, no Python, no AG-tools, no original user JSON, no fresh OAuth or Google endpoints, and does not access WinCred.
- Read-only port discovery uses (a) Win32 iphlpapi GetExtendedTcpTable with TCP_TABLE_OWNER_PID_LISTENER and IPv4 loopback/wildcard filter, (b) Get-NetTCPConnection without the CP54A2 process filter, (c) netstat.exe -ano -p tcp. All filter to exact Language Server PID; reports counts and safe status codes only.
- Before any RPC POST the script rechecks the exact same LS PID+StartTime and fresh listening socket PID ownership; otherwise no CSRF is transmitted.
- Max 4 verified localhost IPv4 port candidates, only Connect-style `HasAuthToken` and then `GetAuthStatus` if confirmed, 2s timeout each, 16 KiB response cap, no proxy, no redirects, no arbitrary method/body. The CSRF and process command line remain in user-PC memory and are never printed or included in ZIP.
- Report only `STEPS.jsonl`, `RECEIPT.json`, `STATUS.txt`, `SUMMARY.txt`, `report.json`. Report flags `identity_verified=false`, `hot_swap_verified=false`. Local auth flag from CP-31-patched LS remains UNTRUSTED.
- Synthetic native MIB_TCPROW_OWNER_PID byte-order math, ZIP hash/CRC, allowlisted stages, and absence of mutation strings were verified in the build environment. Real PowerShell 7 AST/runtime not executed here; do NOT mark host PASS before next user RESULT.
- IPv6-only, named pipes, unknown protocol or no independently owned listening socket → `NO_CONFIRMED_OWNED_IPV4_LISTENER` / INCONCLUSIVE; do not guess ports or scan.

## Parallel Fabric 10.1B state (no merge)
- `main`: b18f31cb39bd655c7fd7e50466069f23d29c957a (10.0B).
- `raif-10-1-worktree-offline-20261010`: a0daf08375b70d202b3dc7b5ab51f894e87d9ae0 (pinned 10.1).
- `raif-10-1a-clone-handoff-20261010`: a5c4e6d2be35588cc875ae070566e3d39baed8d5 (10.1A+10.1B host QA scripts; still not executed on user's Windows).
- `AG_pather` before this doc: 495aa868c7f8a31bbebf5588d87a358312523bd6.
- No merge/PR, no new production/paid inference. 10.1B scripts remain `PASS_STATIC_ONLY / HOST_NOT_RUN`. The already existing `C:\GIT\Rassvet_AI_Fabric` directory was previously reported without .git metadata. Inspect on host before attempting clone. Do not reset, replace or delete it automatically.
- Tower authority: Google Drive CONTROL_TOWER is active by user decision, Github Tower replica remains not production-synchronized, Tower merge requires MTD and preflight. Project cursors remain project-owned. No Tower mutations.

## STOP/GO / Next cursor
AG_pather → CP-54A3 RECEIVE_TRANSPORT_RESULT → G1 confirmed read-only RPC/unsupported interface → CP-54B owned observer.
RAI-FABRIC → 10.1B WINDOWS_HOST_ACCEPTANCE after local clone safety preflight → 10.1C ADVERSARIAL_REVIEW → ISSUE-3 DETACHED_MERGE_REHEARSAL after explicit acceptance.
