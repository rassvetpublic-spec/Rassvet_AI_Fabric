# CP-54A3 — second Windows failure diagnosed; corrected R2 launcher

Date: 2026-10-10. Branch: AG_pather. Status: REPORT_SCHEMA_MISMATCH / R2_PREPARED / WINDOWS_RUNTIME_PENDING.

## User result
- Archive: RAiF_AG_CP54A3_RESULT_20261010_084722_e9bdb4b6.zip, 1856 bytes, SHA256 f388a6a634f63491051e4269a036481af3f5959232604becdec2ec883556ff41; CRC PASS.
- Files: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl. No report.json (launcher did not accept it).
- Status FAILED_SAFELY, reason REPORT_UNSAFE, last_stage validate_report, exit_code 2, probe_exit_code 0, bundle SHA verified, PS7.
- 44 steps: native probe ran its stages and serialized report, then launcher rejected report. Step OK does not prove the actual RPC request succeeded. Without report.json, TCP listener counts and RPC verdict remain UNKNOWN.
- Receipt says no native credential or Antigravity process mutations.

## Root cause (verified by checking both original scripts)
- probe.ps1 emits external_provider_requests_sent_by_script=false.
- Launcher erroneously validated direct_external_provider_requests_sent. Missing JSON property compares unequal to boolean false and causes REPORT_UNSAFE.
- Earlier discovery glob incorrectly sought LocalRpcReadOnly instead of TransportForensics. R2 corrects that mismatch as well.
- This is a schema/version mismatch in our scripts, not evidence of exposed secrets or broken Language Server.

## R2 delivery (source scripts remain local, not in public repository)
- Existing ZIP: RAiF_AG_CP54A3_TransportForensics.zip; SHA256 6140814BF55BBFE70286FB4E2DE3021F1A37FE717472DCF378BF59BCC020EDFE, CRC OK; contains probe.ps1 and README.txt.
- New PS1: RAiF_AG_CP54A3_Run_R2.ps1; size 9290 bytes; SHA256 d73524c6484539f644cf545482f9d835d6cadd527fa7b44d0a3dfb63c1694773.
- Only 3 source lines modified: ZIP file glob, corresponding filename regex, and report field used by safety validator. Bundle hash pin, read-only probe, false-required flags, timeouts and output allowlist unchanged.
- Static source diff, SHA256 pin, CRC and filename consistency PASS. No PowerShell 7 executable in preparation environment; local Windows behavior NOT_YET_VERIFIED.

## Single-command Windows run
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A3_Run_R2.ps1"
Expected sanitized result: C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP54A3_RESULT_<runid>.zip.
Browser-renamed ZIP can be explicitly selected using -BundleZip with the correct local path.

## Cursor
AG_pather → CP-54A3_R2_RECEIVE_REPORT → G1_CONNECT_RPC_TRANSPORT_VERDICT → CP-54B_OR_INCONCLUSIVE.
Rerun does not require re-import of 9 accounts, CP31 patch, CP52 backup, AG-tools or GitHub CI.