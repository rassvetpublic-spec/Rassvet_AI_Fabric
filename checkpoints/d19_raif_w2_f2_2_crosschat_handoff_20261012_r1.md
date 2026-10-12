# Rassvet AI Fabric — W2 F2.2 перенос в новый чат (D19)

**Checkpoint:** `RAIF_W2_F2_2_HOST_521_PASS_MOCK_TIMEOUT_2026_10_12_R1`

**Точный курсор:** `RAIF/W2_F2_2_HOST_UNIT_521_PASS_MOCK_TIMEOUT_DIRECT_PYTHON_DIAG_R1`

**Дата:** 12 октября 2026. ВАЖНО: `HOST_F2_2_BLOCKED`, не `QA_PASS`.

## 1. GitHub и границы

| Объект | Exact pin / статус |
|---|---|
| [DRAFT PR #8](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8) | `OPEN / DRAFT / НЕ MERGED` |
| Ветка | `raif-w2-durable-effect-ledger-20261012` |
| PR HEAD | `4c4dff1433d5b1ccd11c3a6fe45348b4ec7a9395` |
| Git tree | `9535e1c44291d994a6d6f998c0f13ea1705749b7` |
| База PR | `c42a905f904b36c8823930caaedf90951b603651` |
| Текущий main при readback | `cafa6b8dbd3e79a33d714665d424b5f353be3e1c` |
| Сдвиг main после базы | +5 коммитов только docs/checkpoints BPR5, никаких src/tests/scripts |
| [GitHub Windows CI](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38187611702) | `521/521 PASS`, SQLite mock + Codex-mock PASS — **на hosted runner**, не на хосте владельца |
| [Запрос независимой QA R2](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8#issuecomment-6115552984) | `PENDING`, 0 опубликованных PR reviews |
| Merge gate | `OWNER_MTD_CLOSED`; никаких merge/undraft |

## 2. Верифицированная Windows host evidence

**Исходный архив:** `RAiF_W2_F2_2_RESULT_6fbe5f9755d4.zip`, SHA-256 `7c0f28b240495975a7c4bc82ad3424a0ae82db675555bf3386d1d66335ed7716`.

**RUN_DIR:** `D:\ЗАГРУЗКИ\RAiF_W2_F2_2_6fbe5f9755d4`

`manifest.json`: Windows, Python 3.13.14, точный HEAD/tree, `521/521` unit PASS за **75.403 с**. `unittest.log` SHA-256 `49c586e9d6c8536796be1e891906d452c2c300a92f601bd3173e69bf170e3081`, содержит `Ran 521 tests ... OK`. ZIP CRC+sha256 проверены.

**НЕ сделано:** SQLite mock stage 4 `NOT_RUN`, Codex-mock stage 5 `NOT_RUN`, `test_tree_clean=false` потому, что этап 6 не выполнен; это **не** доказательство грязного Git tree. Manifest verdict `BLOCKED`. Ещё один архив `RAiF_W2_F2_2_RESULT_948fe03433ce.zip` — из **другого запуска**, его доказательства не смешивать.

## 3. Resume — подтверждённый тайм-аут

**Архив:** `RAiF_W2_F2_2_SMOKERESUME_RESULT_296a3d806233.zip`; SHA-256 `909e57a631efa696ca1110e17321244b36d58fb23420c4a34b6c6c9d1d2fb415`.

Manifest: `RAIF_RESUME_MOCK_TIMEOUT`, `BLOCKED`, переиспользованы те же 521 unit PASS и точный `unittest.log`; mock и codex-mock `NOT_RUN`, clean-tree `false`. По сообщению пользователя в локальном `smoke-resume-296a3d806233\local-diagnostics` два файла `mock-stdout.local.txt` и `mock-stderr.local.txt` имеют **0 байт**. Следовательно, причина зависания этапа 4 **НЕ УСТАНОВЛЕНА**. Вложенный PowerShell с `Resolve-RAiFPython` в `scripts/demo.ps1` — только гипотеза. Пустой вывод не доказывает отсутствие исполнения.

## 4. Готовое средство диагностики (не запускалось)

Локальный пакет `RAiF_W2_F2_2_DIRECTSMOKE_R1.zip`, SHA-256 `e92c8ac1d9fa2bcefe264f1b1218632d64ee5bc62e6dba71f21716bc513ec272`. Внутри `Run-W2-F2_2-DirectSmoke-R1.ps1`, SHA-256 `c68106ff0c3b1d85a686c2aa29a2578d043802e25bc5a78ba4460b30c05813a1`. Он запускает **только прямой Python CLI synthetic mock/codex-mock**, без оригинального `demo.ps1`, без clone или повторных 521 tests. Результат `RAiF_W2_F2_2_DIRECTSMOKE_RESULT_*.zip`; **ещё не получен**. Даже PASS прямого CLI не подменяет PASS оригинального PowerShell smoke.

**Рекомендуемый следующий ход:** сначала убедиться, что старые R2/Resume процессы закончились; затем запуск DirectSmoke R1 в том же изолированном RUN_DIR `D:\ЗАГРУЗКИ\RAiF_W2_F2_2_6fbe5f9755d4`, с тайм-аутом 90 сек/подкоманду и проверкой SHA-256, получить результат; при ошибке разбирать **один** конкретный подэтап, не запускать full CI или full host suite заново.

## 5. Fail-closed ограничения

- Старый `C:\GIT\Rassvet_AI_Fabric`: последний известный статус **134 tracked WIP**, не трогать.
- Никаких live provider/real OAuth/account переключений, платных API, Tower/Router/CKS/BPR40 authority writes, модификации `main`.
- Independent source QA R2 `PENDING`, owner-host smoke `BLOCKED`, real target effect/powerloss `NOT_TESTED`.
- PR #8 **не сливать** и DRAFT **не снимать** без отдельного exact-SHA MTD.
- GitHub-hosted Windows 521/521 PASS не равен полному Windows-owner F2.2 PASS.

## 6. Команда переноса

> Продолжай Rassvet AI Fabric с checkpoint `RAIF_W2_F2_2_HOST_521_PASS_MOCK_TIMEOUT_2026_10_12_R1`. Курсор `RAIF/W2_F2_2_HOST_UNIT_521_PASS_MOCK_TIMEOUT_DIRECT_PYTHON_DIAG_R1`. PR #8 DRAFT, SHA `4c4dff1433d5b1ccd11c3a6fe45348b4ec7a9395`. На Windows владельца **521/521 PASS**, но SQLite mock висит, Smoke Resume `RAIF_RESUME_MOCK_TIMEOUT`, stdout/stderr по 0 байт. Не повторяй clone/521 tests. Прочитай d19/s19 и host RESULT, продолжи с DirectSmoke R1 (готов, ещё не запущен) в изолированной D:. Не трогай `main` и рабочую C: копию, не merge.

**Гейт:** `HOST_UNIT_521_PASS / MOCK_TIMEOUT / CODEX_MOCK_NOT_RUN / SOURCE_QA_PENDING / F2_2_BLOCKED / OWNER_MTD_CLOSED`.
