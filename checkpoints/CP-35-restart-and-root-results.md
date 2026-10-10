# CP-35 — successful restart; project-root result ZIP contract

Date: 2026-10-10
Branch: AG_pather
Status: USER_RESTART_REPORTED_SUCCESS; DELIVERY_PATH_UPDATED

## Runtime observation
- The user reported "всё запустилось" in response to the CP-35 restart test after patching the Windows Antigravity Standalone language server.
- CP-34 had already confirmed editor access, a successful ping/pong model response and the quota interface.
- This is a user-reported successful reopening; a second model completion after restart was not independently confirmed, so preserve that distinction.
- The Windows language_server.exe binary is already patched; do not patch it again unless its version/signature is checked after an update.

## New mandatory packaging contract
1. The user downloads exactly one ZIP and one PS1 into `D:\ЗАГРУЗКИ`.
2. Launch through a single `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` command.
3. Run/extract under `C:\GIT\Rassvet_AI_Fabric`, with temporary files optionally in `_RAIF_RUNTIME`.
4. Write the **result ZIP directly to the project root**, e.g. `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP36_RESULT_<timestamp>_<id>.zip`. Never require the user to navigate to `_RAIF_RUNTIME` to retrieve results.
5. Exclude root-level diagnostic result ZIPs and the temporary runtime from Git via `.gitignore`; never include real OAuth credentials, personal data, account exports, or process memory in a report.
6. For future packages verify download hash, fail closed on unsupported versions, keep readable status files, and do not change global execution policy.
7. The new output path must be implemented in **each future PS1 launcher**, not merely documented; older CP28/CP30/CP31 launchers still use their original output path if reused.

## Changes
- `.gitignore` updated with root-level RAiF result ZIP ignore patterns and `_RAIF_RUNTIME/`.
- Design specification documents new Windows ZIP+PS1 transfer convention.
- No binaries or users' account files committed. No GitHub Actions invoked for this documentation checkpoint.

## Current cursor
AG_pather / CP-35 RESTART_REPORTED_OK + ROOT_RESULT_CONTRACT_COMMITTED -> CP-36 WINDOWS_ACCOUNT_POOL_PROTOTYPE -> CP-37 STANDALONE_ACCOUNT_SWITCH_TEST.
