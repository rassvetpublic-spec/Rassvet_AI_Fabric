# CP-54A4 / RESULT readback / R2 launcher

Date 2026-10-10. Branch AG_pather.
Status: FAILED_SAFELY_BEFORE_PROBE → MINIMAL_R2_LAUNCHER_STATIC_VERIFIED → WINDOWS_RERUN_PENDING.

## Received Windows result and exact limitations

- Filename: RAiF_AG_CP54A4_RESULT_20261010_090519_8b8e2660.zip
- Size: 1508 bytes; SHA256 5b664eca742ca434033fba7e0071ec3c4be409e4dd4ebb85f7dd596f78bbd457; ZIP CRC PASS.
- Allowlist only STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl; no report.json, because probe.ps1 never ran.
- Receipt: protocol RAIF_AG_CP54A4_MULTI_LS_READONLY; status FAILED_SAFELY; reason BUNDLE_CONTENT_INVALID; last_stage validate_zip_entries; exit_code=2; probe_exit_code=null; source_zip_sha256_verified=true; powershell_major=7; result_location=downloads_root.
- STEPS.jsonl: 21 valid JSON lines; check Git checkout / downloads root / root segregation / find ZIP / pinned SHA all OK; validate_zip_entries failed at elapsed_ms=112; packaging completed at elapsed_ms=401.
- No native credentials modified and no Antigravity process modifications reported by launcher. No Language Server instances, TCP listener or RPC were inspected: **G1 remains UNKNOWN**.

## Root cause verified against source ZIP and launcher

- Source ZIP SHA256 A0ED0009659C91D0843B1A465E2CF3F37759607278D9CE2573CF919F302B8DB7, size 6995 bytes, CRC PASS.
- Archive has exactly two correct top-level entry paths: probe.ps1 and README.txt, no directories or extras.
- Original launcher used `$inspect.Entries | ... | Sort-Object`, then enforced sorted index 0 = README.txt, index 1 = probe.ps1. PowerShell Sort-Object is culture-sensitive/case-insensitive by default: probe precedes README. Thus an intact ZIP was rejected.
- Fixed check is *order-independent and case-sensitive*: exact count=2 and `-ccontains 'README.txt'` and `-ccontains 'probe.ps1'`. Still rejects unexpected names, wrong case, missing files, and extras. Does not bypass the checksum or allowlist.

## R2 delivery

- Keep existing RAiF_AG_CP54A4_MultiInstanceTransport.zip exactly as-is in D:\ЗАГРУЗКИ.
- New conversation-only launcher: RAiF_AG_CP54A4_Run_R2.ps1, size 11323 bytes, SHA256 CACEE9099276C68EC1CDCE11CE544CDAF8B47899EE4FAB38E82A3999AF800D2F.
- The only functional alteration is validate_zip_entries: order-independent exact-name check. No edits to probe.ps1, WinAPI/CIM/TCP code, RPC call allowlist, report schema, source ZIP SHA or output locations.
- Static diff + ZIP CRC/hash + schema-key readback PASS. No PowerShell 7 runtime in analysis environment, so **Windows execution of R2 is not yet verified**.
- One command: `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_Run_R2.ps1"`.
- Outputs directly in Downloads: `D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_RESULT_<runid>.zip` and `D:\ЗАГРУЗКИ\RAiF_AG_CP54A4_RUNTIME_<runid>\`.
- Git root `C:\GIT\Rassvet_AI_Fabric` only read; no tokens in reports, no processes killed, no account rotation or external provider calls.

## Parallel Fabric scope
- Main not merged; 10.1B host QA still pending. No CI or code changes in public GitHub in this step.
- Control Tower authority remains Drive-defined; no tower mutation or merge.

## Cursor
AG_pather → CP-54A4_R2_RECEIVE_MULTI_LS_RESULT → DETERMINE_PER_INSTANCE_TCP_AND_CONNECT_RPC_VERDICT → CP-54B_G1_OR_INCONCLUSIVE.
