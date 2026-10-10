# CP-43 — Successful Windows PowerShell 7 staged preflight

Date: 2026-10-10. Branch: AG_pather.

## Received evidence
- User result ZIP: RAiF_AG_CP42_RESULT_20261010_050235_e17e5a00.zip.
- Result ZIP SHA-256: 698feaccdd62c68f7f87068d452229ea991da1f6f2a557735690d6a3f300a1a2.
- ZIP CRC valid; 5 allowed files: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json.
- Receipt protocol RAIF_AG_CP42_PWSH7_READONLY, schema 1, status SUCCESS, exit_code 0, probe_exit_code 0, source ZIP hash verified, PowerShell major 7, output in project root.
- STEPS.jsonl: 40 structured events from launcher and probe; all observed states are start/ok, no failure codes. Run to package completion ~2.5 seconds as reported by elapsed_ms (not a billing metric).

## Environment
- Windows, PowerShell 7, project directory exists.
- Antigravity running: 6 process entries, language_server running: 1 process entry at capture time.
- The patched language_server.exe has size 165675008 bytes; SHA-256 b23c730a3b23953a7e46851593a5013bc888c524c8965cbb21618fc51122d81e, matching post-patch CP-33 evidence. Read-only report metadata; the binary itself was not uploaded.
- Credential Manager: native Antigravity target exists, isolated RAiF account targets count 0. Neither secrets nor credential values were collected.
- Account manifest NOT detected beside CP42 launcher (accounts_file.present=false). There is no positive or negative assessment of its schema or token validity from this run.
- Local RAiF registry not present; no pending recovery.
- Git command not on PATH and .git metadata absent in the checked project directory. This does not prove Git is not installed elsewhere. Before any local git operations, inspect location/clone state without guessing.
- No provider requests, hot-switches, process modification, or credential modification were performed.

## Decision
- CP42 PowerShell-only launcher and structured stage logging validated successfully on user's Windows machine.
- Stop repeating these environment diagnostics. Next work should target account import/pool proof of concept using synthetic data first.
- Need to locate the account manifest on the user's Windows machine for further local-only preview; do NOT copy any real credentials into GitHub, chat reports or artifacts.
- Import into RAiF isolated vault must require explicit user consent and cannot be mistaken for switching live Antigravity account.
- CP35 successful restart and CP34 model/quota access remain previously observed; hot swap is NOT verified.

## CURSOR
AG_pather / CP-43 PWSH7_PREFLIGHT_SUCCESS -> CP-44 LOCAL_ACCOUNT_MANIFEST_DISCOVERY_AND_SAFE_PREVIEW -> CP-45 WINDOWS_VAULT_IMPORT_OPT_IN -> CP-46 STANDALONE_SESSION_INTEGRATION_RESEARCH.
