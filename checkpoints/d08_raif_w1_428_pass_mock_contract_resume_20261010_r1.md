# RAiF W1 — Windows 428/428 PASS, mock harness contract mismatch; W1-R2 resume

Дата: 2026-10-10. Владелец checkpoint: `rassvetpublic-spec/Rassvet_AI_Fabric` / `AG_pather`. Предшественник `checkpoints/s07_raif_w0b_w1_isolated_handoff_20261010_r1.json`; источник — только полученный пользовательский RESULT.

## Принятый W1 RESULT с точной областью PASS
- Имя: `RAiF-W1-RESULT_20261010_134700_872266a9.zip`; SHA-256 `61535dd5ec1622d985e9ded2c321a21f0191c742dcf5ae77fa8b0bb4fb5d795a`. ZIP CRC PASS, **ровно 5** allowlisted членов `STEPS.jsonl, RECEIPT.json, STATUS.txt, SUMMARY.txt, report.json`.
- Запуск `20261010_134700_872266a9`, SOURCE pin `8dc6ee32eabd3334012763bac8e641f682e478c6`, tree pin `8d2a0d0c195a3ffbb64cf26ba46e906936261894`, 289 безопасных regular файлов. Клонирование в НОВЫЙ `D:\ЗАГРУЗКИ\RAIF_W1_RUNTIME_20261010_134700_872266a9\isolated_source` завершилось, checkout перед тестами был чист. Пользовательский клон `C:\GIT\Rassvet_AI_Fabric` не затрагивался согласно очищенному отчёту.
- `UNITTEST / EXACT_428_WITH_WORKTREE_20` PASS — **428/428** Windows тестов, 20 `test_worktree_review`, skipped=0. Это отдельный пользовательский Windows evidence; не переписывать в hosted CI.
- `SAFE_STOP / LOCAL_MOCK_SUBMIT_FAILED` — конечный `BLOCKED`; `mock_queue=NOT_RUN`, `codex_mock=NOT_RUN`, `host_acceptance=NOT_RUN`. Проверка чистоты после тестов вообще не была достигнута: `checkout_clean_after_tests=false` — дефолт, **не доказательство грязного дерева**.
- Причина установлена по точному коду поставленного `w1_host_acceptance.py` и `src/rai_fabric/store.py` в `main`: `W1.demo()` проверял `doc.get('task_id') == tid`, тогда как `FabricStore.submit()` и `FabricStore.get()` возвращают `_view` с полем `id`. Ошибочный check также присутствовал для `run-once` и `task`. `checked_cli_json` успел проверить exit code 0 и корректный JSON; остановка в harness, **не доказанная ошибка SQLite**.

## [--] → [==] → [++] → [~~] исправление без повторного расхода
- **[--]** Не запускать заново уже успешные 428 тестов и публичный clone, не интерпретировать дефолтный `checkout_clean_after_tests=false` как испорченный checkout.
- **[==]** Подготовлен новый `RAiF-W1-SmokeResume-R2.zip`, SHA-256 `e2702e50e6140111849a7f31454eda6c492f48a281eb763bd4445e4ee041ed07`; новый `Start-RAiF-W1-SmokeResume-R2.ps1`, SHA-256 `fc6b2226a5a52e11ae739fd22909440ed3546d0cdd77c4fe00b4fd554db1c775`. ZIP CRC PASS, 4 allowlisted members, SHA всех payload PASS. **30/30 локальных тестов** запуском из ZIP на Linux, Windows PS7 AST/host для R2 пока NOT_RUN.
- R2 проверяет хэш старого W1 RESULT, исходный `source pin + tree pin`, origin и clean status уже существующей изолированной копии; при missing/drift/dirty блокируется. Два новых smoke сценария — `mock` + `codex-mock` в уникальных SQLite каталогах `D:`, с проверкой настоящего CLI контракта `id/status/provider/checkpoint.evidence.simulation`. После smoke ещё один exact readback и clean status. Ни Git clone/fetch, ни retest 428, ни редактирования старого runtime.
- `-Apply` разрешает **только локальные mock-проверки**; не является согласием на реальные модели/сессии, OAuth, provider calls, merge, смену identity или запись в Башню. Не запускать R2 если старый `RAIF_W1_RUNTIME_20261010_134700_872266a9` или W1 RESULT отсутствуют: сначала отдельный операторский source-recovery gate.
- **[++]** После пользовательского W1-R2 RESULT проверять 2 успешных smoke + целостность предыдущего 428/428 и clean postcheck. Только тогда `W1_OFFLINE_CORE_ACCEPTED_COMPOSITE` и курсор `W2/10_4_CP54D_DURABLE_TASK_RECOVERY`.
- **[~~]** MASTER PLAN W0–W5 остаётся, W1 не откатывается: `W1/UNITTEST_428_PASS_MOCK_HARNESS_R2_HOST_PENDING`. Все неподтверждённые provider/authority gates остаются отдельными.

## Запуск W1-R2 на Windows
Нужно сохранить ZIP и PS1 в `D:\ЗАГРУЗКИ` рядом с прошлым `RAiF-W1-RESULT_20261010_134700_872266a9.zip`, **не удаляя** старую папку `RAIF_W1_RUNTIME_20261010_134700_872266a9`. Запуск:

`pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\Start-RAiF-W1-SmokeResume-R2.ps1" -Apply`.

Результат: один `RAiF-W1R2-RESULT_<runid>.zip` (5 безопасных файлов) в `D:\ЗАГРУЗКИ`. Не размещать raw stdout/stderr или скрытые credentials в GitHub.

**После W1-R2:** W2 Fab 10.4 — checkpoint/lease, restart и UNKNOWN_OUTCOME без слепого replay; отдельный Windows QA. G2 identity CLOSED. Tower GitHub `production_sync=false`; `main` и Tower untouched.
