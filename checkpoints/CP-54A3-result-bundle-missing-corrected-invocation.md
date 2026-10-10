# CP-54A3 result — ZIP discovery bug, no transport probe executed

Date: 2026-10-10. Branch: AG_pather.
Status: FAILED_SAFELY / USER_RERUN_NEEDED_WITH_EXPLICIT_BUNDLE_PATH.

## Received Windows result, verified

- Archive: `RAiF_AG_CP54A3_RESULT_20261010_084259_7c3fbce6.zip`.
- SHA-256: `c1456d1d5a73e8e34f5c304799a4d45acbd99969a8a2caad853ba29e860b7e7a`; file size 1308 bytes.
- ZIP integrity: CRC OK; strictly STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl. No report.json because the payload was never invoked.
- Receipt: protocol RAIF_AG_CP54A3_TRANSPORT_READONLY, status FAILED_SAFELY, reason BUNDLE_MISSING, last_stage find_bundle, exit_code 2, source_zip_sha256_verified=false, zip_candidates_found=0, powershell_major=7, probe_exit_code=null.
- STEPS.jsonl: 13 events; check_pwsh7 and check_project_root pass, runtime created, `find_bundle` fails; result receipt/archive generated successfully.
- No native credentials/processes mutated by this launcher. No listeners inspected, no RPC called and no evidence of interface status collected.

## Root cause — source code readback (exact)

- CP-54A3 package actually delivered as `RAiF_AG_CP54A3_TransportForensics.zip`, SHA-256 pinned in PS1 `6140814BF55BBFE70286FB4E2DE3021F1A37FE717472DCF378BF59BCC020EDFE`; ZIP CRC OK, contains probe.ps1, README.txt.
- The handed-off `RAiF_AG_CP54A3_Run.ps1`, SHA-256 `0925D550FE231285650F36FE21A977B59ACBE9B30CB961CB64019E84993596D3`, incorrectly searches with `-Filter 'RAiF_AG_CP54A3_LocalRpcReadOnly*.zip'` and regex `^RAiF_AG_CP54A3_LocalRpcReadOnly(?: \([0-9]+\))?\.zip$`, copied from CP54A2.
- The PS1 includes a supported `-BundleZip` parameter that bypasses that filename filter while retaining SHA-256 verification and read-only diagnostics. Therefore do not rebuild/redownload a package just to correct this mismatch.

## One-line rerun (PowerShell 7 on user's Windows)

`pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A3_Run.ps1" -BundleZip "D:\ЗАГРУЗКИ\RAiF_AG_CP54A3_TransportForensics.zip"`

If the downloaded ZIP was renamed by the browser (e.g. `(1)`), pass its actual exact local path. The pinned SHA-256 prevents confusing unrelated archives.

Expected result (strict project root location):
`C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP54A3_RESULT_<runid>.zip`.

## Important limits

- BUNDLE_MISSING is a launcher naming bug, **not** an LS or RPC protocol failure.
- This host result does not establish presence/absence of IPv4 listeners and cannot advance G1.
- No new CI or Github code commit required. Do not repeat CP-31 patch, CP46 import or CP52 rollback preparation. Test only the existing read-only CP54A3 probe.
- The bundle and PS1 remain off the public repository. Neither user credentials nor source binaries published here.

## CURSOR

`AG_pather / CP-54A3_BUNDLE_FILENAME_BUG_DIAGNOSED → CP-54A3_RETRY_WITH_BUNDLEZIP → RECEIVE_TCP_PORT_AND_RPC_REPORT → CP-54B_G1_IF_CONFIRMED`.
