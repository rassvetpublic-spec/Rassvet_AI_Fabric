# RAiF — CP-54B3: Windows SAFE_FAIL / V2 offline handoff
**Дата:** 2026-10-10. **Владелец:** `rassvetpublic-spec/Rassvet_AI_Fabric`, ветка `AG_pather`. Предыдущий handoff: `RAIF_CHAT_HANDOFF_CP54B3_2026-10-10_R1`. Код observer и тестов: `fd02aed65d04022160518faf4f857865ab3aa59f`.

## Полученный Windows RESULT (исходный V1)
- `RAiF-CP54B3-RESULT_20261010_072925_8e043621.zip`: SHA256 `b5b3494370e3921be6f6db3ed063f0c9d087b78b5d60cdd299e39e205823ecb8`, ZIP CRC PASS; ровно 5 обязательных файлов.
- `STEPS.jsonl`: 6 событий, 5 PASS и 1 FAIL. PASS: CREATE_RUNTIME, HOST_GATE, PINNED_ZIP_SHA256, ZIP_STRICT_ALLOWLIST_AND_EXTRACT, PYTHON_SOURCE_SHA256. Последнее событие: `BOUNDED_SAFE_ABORT/FAIL`.
- `STATUS.txt = BLOCKED`; `report.json.verdict=SAFE_FAIL_NO_LIVE_CALL`; тесты `0/11`. `live_rpc_attempts=0`, `native_credentials_read=false`, `account_switches=0`, `authority_changes=0`. Это безопасное прекращение, **не** успешная Windows-приёмка.
- Причина **не определима** по sanitised RESULT: V1 скрывает ошибку общим catch. Сбой мог быть при проверке либо копировании `native_rpc.py` из `C:\GIT\Rassvet_AI_Fabric` или подготовке локального модуля после этого. Не объявлять подтверждённую причину без наблюдения.

## Корректировка V2 без повторения прежних испытаний
- Сформирован self-contained `RAiF-CP54B3-v2.zip`, SHA256 `08ab715f3e94ffadd59d60655f7af51cacb2cb4fd82b3052fab2d75e728bbd68`. Шесть members, включая `native_rpc.py` с SHA256 `9705f27460278d9f51534ed9aadafb396999d8e2191a993166b2f797ccb26bf1`; исходники соответствуют ранее проверенному GitHub code commit.
- Новый `Start-RAiF-CP54B3-v2.ps1`, SHA256 `6a36308680c6b42b38aa9bffc01c11095ab3217c50017c300153c3ee53c2fca2`. Больше **не читает C:\GIT вообще**, использует pinned ZIP и шесть точных SHA; фиксирует stage + безопасный код ошибки, не записывая сырой stderr/credentials.
- На изолированном Python `-I -B` из V2 ZIP `11/11 PASS` (0 errors, 0 failures, 0 skipped), CRC/hash/allowlist сверены. Windows PowerShell AST/runtime V2 здесь **не проверен**: `pwsh` в sandbox отсутствует. Поэтому статус `V2_READY_FOR_HOST_OFFLINE_SYNTHETIC`, а не `HOST_PASS`.
- Обе V2 поставки сохранить непосредственно в `D:\ЗАГРУЗКИ`, запуск: `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\Start-RAiF-CP54B3-v2.ps1"`. Новые runtime и ZIP RESULT только `D:\ЗАГРУЗКИ`. RESULT содержит ровно `STEPS.jsonl,RECEIPT.json,STATUS.txt,SUMMARY.txt,report.json`.
- В пакете НЕТ живого `GetUserStatus`, сетевых provider-вызовов, операций с аккаунтами или изменениями authority. Тестирование не требует AG-tools.

## Факт и границы
- Прошлый source Windows CI: [run 38034030604](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38034030604) SUCCESS, `190/190`. Новую CI задачу ради упаковки **не запускать**.
- `IDENTITY_UNVERIFIED`; сопоставление с любым из 9 RAiF Vault account IDs и pool eligibility **не подтверждены**.
- CONTROL TOWER PR #29 = OPEN/DRAFT NONCANON; ни main, ни Tower/Router/BPR40/CKS не менялись. Гарантий Windows host QA 10.1B нет.
- Доказательства V1 отказа не превращают его в PASS; V2 локальная проверка не становится PASS Windows-хоста без фактического RESULT.

## Передача и следующий курсор
1. **Сейчас:** `AG_pather / CP-54B3 / RESULT_V1_SAFE_FAIL_V2_STATIC_REPACK_READY`.
2. **Далее:** `CP-54B3 / WINDOWS_OFFLINE_SYNTHETIC_V2_RESULT_READBACK`. Проверить факт запуска на Windows по пяти файлам, SHA, exit codes, фиксированному коду причины.
3. **После успешной V2 Windows-синтетики:** `CP-54B3 / EXPLICIT_G2_IDENTITY_READ_GATE`. **Не запускать живой RPC без отдельного явного gate**; тесты не доказывают identity.
4. **Параллельно Fabric:** `10.1B / WINDOWS_HOST_ACCEPTANCE`; до полной QA никаких merge или detached rehearsal promotion.
5. **Handoff:** всегда исходить из точного project checkpoint, не из NONCANON Tower pointer и не из неподтверждённого текущего локального Git checkout.
