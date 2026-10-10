# RAiF BIGWAVE 02 — Source+Windows CI 265 PASS; host read-only diagnostic R2

Дата: 2026-10-10. Владелец: `rassvetpublic-spec/Rassvet_AI_Fabric`, `AG_pather`.
Предыдущий проектный checkpoint: `RAIF_10_3_POST_MERGE_TOWER_BPR5_READBACK_20261010_R1`.
Источник: [commit 975c61a5](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/commit/975c61a5b77ca69a674df994fbcab0d372c62ac9); исходный HEAD `4032b73bcdbc2e355898953439194e7a077d90e0`.

## Что выполнено одной волной
- Новый `src/rai_fabric/host_diagnostic_10_3.py`: ограниченный read-only Git inspection **одного существующего** `C:\GIT\Rassvet_AI_Fabric` с фиксированными редактированными кодами. Не выполняет clone/fetch/checkout/reset/merge/side effects, не читает credentials, не запускает код из клона. При старой ошибке `HOST_CLONE_READ_FAILED` теперь различает, например, `GIT_SAFE_DIRECTORY_REJECTED`, ACL, root mismatch, origin, pin, грязную или ignored директорию, смену HEAD в процессе. До Windows RESULT **реальная причина остаётся UNKNOWN**.
- `src/raif_ag_supervisor/continuity.py` защищает JSON от `NaN/Infinity`, проверяет все предковые reparse/junction компоненты каталога и выдаёт только фиксированные ошибки. SHA файла — целостность, **не подпись** и не authority. Нет полноценного доказательства crash-powerloss durability.
- `tests/test_bigwave02_host_diagnostic.py` и `tests/test_bigwave02_continuity_faults.py`: **28 новых** тестов (negative, safe output, concurrency guards, no-effect replay, exact pin, sanitized Git stderr). Локально `28/28`, общий прежний+новый набор `75/75`, ноль ошибок.
- Один штатный [Windows CI #38051697374](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38051697374) `SUCCESS` **265/265**, точный source SHA `975c61a5b77ca69a674df994fbcab0d372c62ac9`. Все 28 новых тестов включены; лишние CI вручную не запускались.

## Поставочный контракт (Windows)
- Архив `RAiF-BIGWAVE02-CP54D-F10_3-R1.zip`, SHA256 `519711f07b5575e6da40ea175a459bb36cd806d7802212f20aa1373d4c8d03b8`. Девять разрешённых файлов; ZIP CRC PASS; все payload SHA проверены по MANIFEST.
- Launcher **`Start-RAiF-BIGWAVE02-R2.ps1`**, SHA256 `5a91bedd743f66bc355c93d9c81a13aba5f9a7fac4994ab41b4decc684097b26`. Ранний R1 launcher не использовать: R2 явно загружает .NET ZipFile assembly.
- Сохранить оба в `D:\ЗАГРУЗКИ`, выполнить `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\Start-RAiF-BIGWAVE02-R2.ps1"`.
- Runtime `D:\ЗАГРУЗКИ\RAIF_BIGWAVE02_RUNTIME_<id>`, RESULT `D:\ЗАГРУЗКИ\RAiF-BIGWAVE02-RESULT_<id>.zip`. Ровно пять разрешённых файлов `STEPS.jsonl / RECEIPT.json / STATUS.txt / SUMMARY.txt / report.json`. Без секретов, full Git stdout/stderr, логов командной строки и локальных личных путей.
- Отчёт возвращает `PARTIAL` намеренно даже после успешных 28 тестов и диагностики: **это не полная Windows QA 10.3**, не подтверждение работы live Antigravity/Google, не доказательство реального отката. Текущий host run **NOT_RUN**; PowerShell 7 AST/runtime здесь не проверялся.

## Согласование интеграции и Башни
- Fabric `main=8dc6ee32eabd3334012763bac8e641f682e478c6` уже содержит R5 интеграцию, тестируемую ранее [428/428](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38049455516), и точное совпадение tree PR HEAD с merge-коммитом. Не повторять старый Codex 10.0B и 10.1B/428 механически.
- История `AG_pather` расходится с `main`, а новый диагностический source находится **только в AG_pather**. Не делать merge без отдельного gate.
- PR #4 объединён аккаунтом владельца; его документ `MTD 011011` одобрял только staging+PR. Доказательство отдельного merge MTD во внешних источниках не найдено: `MERGE_AUTHORITY_EVIDENCE_UNVERIFIED`, не автоматически `UNAUTHORIZED`.
- Действующая Tower authority — Google Drive CONTROL_TOWER. GitHub Tower `production_sync=false`; PR #29 открыт draft pointer; BPR5 R7 — `CANDIDATE_HARDENED_IN_FLIGHT`. Не изменять Router/BPR40/CKS/authority.

## Курсоры и не повторять
**Выполнено:** `AG_pather / BIGWAVE02_SOURCE_CI_265_PASS_PACKAGE_STATIC_VERIFIED`.

**Далее:** `AG_pather / BIGWAVE_02_WINDOWS_READONLY_DIAGNOSTIC_RESULT_READBACK` → только затем решать безопасную QA 10.3 и конкретный препятствующий gate. Отдельный Fabric курсор: `10.3/POST_MERGE_HOST_STATE_AND_PERMISSION_RECONCILIATION`.

`G2 Identity=CLOSED`. Нет разрешения на live `GetUserStatus`, Credential Manager writes, account rotation, реальный rollback, stream replay, merge или изменение authority. Не повторять CP31/46/52D/54A5/B1/B3, Codex 10.0B и BIGWAVE R1.
