# RAiF — передача в новый чат после CP-54B2 (R1)

**Дата:** 2026-10-10. **Состояние:** handoff / project-owned checkpoint, не релиз, не принятие hot-switch. **Ветка-владелец:** `rassvetpublic-spec/Rassvet_AI_Fabric` → `AG_pather`.

## 1. Контекст для продолжения

Мы строим **Rassvet AI Fabric** с двумя независимыми рабочими линиями: (A) собственный Windows-only RAiF Antigravity Supervisor, **без AG-tools**, (B) основной Fabric Codex/Worktree. Используются Windows 10/11 x64 и PowerShell 7 для нового AG-пакета. Не повторять выполненный Codex turn 10.0B, импорт 9 учётных записей CP-46, патч CP-31 или DPAPI snapshot CP-52D.

**Новый чат должен начать с актуального readback project HEAD и соответствующего чекпойнта, а не с повторного импорта или прежних экспериментов.**

### Подтверждённое на Windows

| Evidence | Verdict | Что доказано |
|---|---|---|
| CP-31 | VERIFIED HISTORICALLY | рабочий патченный `language_server.exe` установленного Antigravity Standalone 2.22.0; повторно не патчить |
| CP-46/48 | STORAGE_READY | 9 opaque профилей в собственном RAiF Windows Credential Manager и Registry, отсутствие pending import |
| CP-52D | DPAPI_ROUNDTRIP_PASS | оригинальный native credential защищён локальным DPAPI CurrentUser v2, exact roundtrip; **реальный откат живой сессии не испытан** |
| CP-53 | SAFE_FAIL | два запуска завершились до записи native credentials: **0 фактических переключений**; ошибочная зависимость от устаревшего AG-tools cache устранена из архитектуры |
| CP-54A5 | NATIVE_HTTPS_CONNECT_RPC_PASS | локальный HTTPS Connect-RPC `HasAuthToken` и `GetAuthStatus` на реально работающем LS; не официальный стабильный публичный API |
| CP-54B1 | NATIVE_QUOTA_READ_PASS_WITH_SCOPE | реальный HTTPS `RetrieveUserQuotaSummary` одного LS, две группы и четыре окна; исходный RESULT ZIP валиден |
| CP-54B2 | SOURCE_WINDOWS_CI_SUCCESS | собственные `quota_observer.py`, opt-in native quota RPC, fail-closed tri-state `disabled`; Windows CI SUCCESS |
| UI review | DISPLAY_CROSSCHECK_PASS_4_OF_4 | скриншот встроенных Antigravity Models & Usage совпадает с четырьмя процентиками RaIF после округления |

### Подтверждённые наблюдения квот в CP-54B1

- Gemini, **5h**: fraction 0.6866705 → **68.66705%**; нативный Antigravity UI показывает **69%**.
- Gemini, **weekly**: fraction 0.6757333 → **67.57333%**; UI показывает **68%**.
- Claude/GPT, **5h**: fraction 1.0 → **100%**; UI **100%**.
- Claude/GPT, **weekly**: fraction 1.0 → **100%**; UI **100%**.
- Согласованность **4/4 на уровне округления UI**, но снимки могли быть сделаны не одновременно.
- Quota report: `disabled=null`, `reset_utc=null`. Это не доказательство доступности следующего запроса. `AccountPool` теперь трактует отсутствие флага disabled как **UNKNOWN**, а не разрешение выбирать аккаунт.
- `GetUserStatus` вернул **RESPONSE_TOO_LARGE** при прежнем лимите 16 KiB; это ограничение буфера наблюдателя, не доказательство ошибки авторизации.
- Работающий экземпляр LS, подтвердивший read-only RPC и квоты, — PID **19972** на момент проверки. PID временен и **не переносится в новый чат как текущий**.
- Локальный `HasAuthToken=true` и `hasValidAuth=true` **не являются независимым provider proof**, поскольку hasValidAuth бинарно изменён ранее в CP-31.
- `account_identity_verified=false`, `provider_access_verified=false`, `hot_swap_verified=false`, `inflight_resume_verified=false`. **Ни одна из девяти RAiF записей пока не подтверждена как активная сессия**.

## 2. Где код и доказательства

- Native HTTPS core: `src/raif_ag_supervisor/native_rpc.py`. На CI синтетический transport test PASS.
- Quota policy: `src/raif_ag_supervisor/pool.py`, `quota_adapter.py`, `quota_observer.py`. Трёхзначный disabled: true/false/null (unknown); unknown не READY.
- Privacy/synthetic tests: `tests/test_native_rpc.py`, `tests/test_quota_adapter.py`, `tests/test_native_quota_observer.py`.
- Primary evidence: `checkpoints/CP-54B1-quota-proven-CP-54B2-eligibility-hardening.md`, дополнен результатом UI 4/4 на коммите `0e63534525d157246daa5c71e1bdb33c8cf653dd`.
- Windows CI: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38031805893 — **SUCCESS** для CP-54B2 source commit `599c7feb876ffe5f2a6372de876bb4f7082c4b28`.
- Отчёт CP54B1: `RAiF_AG_CP54B1_RESULT_20261010_093406_1d9e6b94.zip` (только локальный пользовательский RESULT, не GitHub); SHA256 `7cdd29068c46e99094fe647f23644a892b15e643f95e5a4a599012a1fac5edeb`; PowerShell 7; 58 событий 0 ошибок.
- Статический protobuf-аудит: `design/CP-54A-native-language-server-rpc-binary-findings.md` — 324 методов LS + HostBridge GetOAuthToken getter, явного SwitchAccount/SetAuthToken RPC не обнаружено; не доказывает отсутствия иных внутренних путей.

## 3. Текущий единственный рабочий курсор AG

`AG_pather → CP-54B3 / BOUNDED_ACTIVE_ACCOUNT_IDENTITY_EVIDENCE → CP-54C / USER_CONTROLLED_HANDOFF_GATE`.

**Задача CP-54B3:** подтвердить, какая из девяти защищённых учётных записей реально активна в Standalone, не экспортируя email/refresh/access tokens и не ошибочно прикрепляя квоты к другому RAiF handle. Исследовать достаточную read-only информацию ответа `GetUserStatus` с **ограниченным более крупным буфером, обработкой только в памяти и строгой редактирующей сериализацией**. При необходимости использовать подтверждённый безопасный источник identity. Не объявлять доказанной identity только по совпадению процентов, UI или локальному флагу valid auth.

**Acceptance G2-B3:** независимое привязывание активного профиля к конкретному RAiF opaque ID с локальным сравниванием / выдачей лишь статуса, либо честный `IDENTITY_UNVERIFIED/UNSUPPORTED`. В публичный GitHub — только тесты на синтетике и redacted aggregate.

**CP-54C** только после identity+permission+rollback gates: сначала один альтернативный профиль и возврат к исходному (отдельное явное согласие), затем при успехе максимум пять профилей за 60 секунд тестовых действий. Нет доказанного live account switch или stream continuity. Никаких авто-ротаций для обхода условий поставщика.

## 4. Линия основного Fabric — независимо от AG

- `main`: `b18f31cb39bd655c7fd7e50466069f23d29c957a` — Codex 10.0B, первый реальный Windows turn + checkpoint; **не повторять turn**.
- `raif-10-1-worktree-offline-20261010`: `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0` — offline worktree review, 20 тестовых методов, user Windows acceptance НЕ завершена.
- `raif-10-1a-clone-handoff-20261010`: `a5c4e6d2be35588cc875ae070566e3d39baed8d5` — 10.1A+10.1B host QA скрипты, **PASS_STATIC_ONLY / HOST_NOT_RUN**, включает ветку 10.1; main не тронут.
- `AG_pather` отдельно; старые `ag-ci-*` ветки — исторические тестовые снапшоты.
- Issues #1 (Windows/merge QA), #2 (Hot-Switch RFC), #3 (merge coordination) остаются отдельными. Полный isolated detached merge rehearsal и комбинированная Windows QA должны быть выполнены ДО merge.
- Fabric cursor: `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE → 10.1C_ADVERSARIAL_OFFLINE_REVIEW → ISSUE-3_DETACHED_MERGE_REHEARSAL`. Не делать merge в main без отдельного разрешения.

## 5. Новый контракт локального Windows обмена

- Пользователь подтвердил: `C:\GIT\Rassvet_AI_Fabric` теперь **настоящий Git-клон**, его не использовать как каталог временных результатов и не сбрасывать/клонировать поверх.
- Все новые исходные ZIP, Run.ps1, runtime-директории и RESULT ZIP — **непосредственно в `D:\ЗАГРУЗКИ`**.
- Один ZIP + один PS1, запуск `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\<RUN_NAME>.ps1"` с необходимыми параметрами opt-in.
- Полный `STEPS.jsonl`, `RECEIPT.json`, `STATUS.txt`, `SUMMARY.txt`, `report.json`. Никаких сырого userinfo, cmdline, CSRF, токенов, email, локальных DPAPI snapshots, полных provider response bodies.
- Не повторять ошибки предшествующих launcher: несовпадающие имена ZIP; разные поля probe/report validation; сортировка ZIP entry names, зависящая от культуры/регистра; ложный fail при >1 LS. Все стадии/флаги валидировать статически перед выдачей.
- Не запускать ещё один ZIP только для подтверждения уже доказанного HTTPS RPC или квот; следующий реальный тест лишь для обоснованного identity gate.

## 6. Башня / BPR40 — сохранение границ

- Актуальная Control Tower GitHub реплика (private): `rassvetpublic-spec/CONTROL_TOWER`; действующая authority по её `control/current.yaml` — **Google Drive папка CONTROL_TOWER**, ID `1d3boKYmIGgOqLEZB3nlHTt-sTl8i9QnW`, конечный ответственный USER.
- Router v18 и BPR40 4.0.3 RELEASED (на дату последнего readback); НЕ начинать BPR40 R3 и не делать promotion в канон от имени Fabric.
- Tower хранит **ссылки/проекции** проекта, а **проектные курсоры принадлежат Fabric**. GitHub Tower `production_sync=false`; совпадение logical revisions Drive↔GitHub не проверено, зеркальность/production sync **не заявлять**.
- GitHub Tower main SHA при предзаписи: `b8d0e4f255b888a134091122b2d1db0a2c7d616c`; PR #25 (R3 plan) и #27 (Integration Readiness R2) уже были merged с пометкой MTD в истории, но это НЕ полномочие мержить новые checkpoint PR.
- Контроль Tower: `TOWER_SYNC_PREFLIGHT` перед содержательной мутацией, `merge_requires: MTD`, no blind pull/reset/rebase/force, no automated duplicate volatile cursor authority.
- Этот handoff — **информационный non-canon pointer**, не выдача нового authority для Tower, CKS, RULESHUB или BPR40.

## 7. Как начать новый чат

> Продолжай Rassvet AI Fabric с чекпойнта `RAIF_CHAT_HANDOFF_CP54B2_2026-10-10_R1` из GitHub `rassvetpublic-spec/Rassvet_AI_Fabric`, ветка `AG_pather`. Сначала прочитай этот проектный чекпойнт, актуальный HEAD и Tower pointer. Курсор `CP-54B3 / BOUNDED_ACTIVE_ACCOUNT_IDENTITY_EVIDENCE`. Не повторяй CP-31, CP-46, CP-52D, CP-54A5/54B1, не требуй AG-tools. Подготовь собственный минимальный безопасный observer с полным логированием; Windows runtime и RESULT только в корне `D:\ЗАГРУЗКИ`. Параллельный Fabric 10.1B остаётся HOST_NOT_RUN. Не меняй main и не публикуй проектные курсоры в CKS Canon или Tower authority. Продолжи сначала с GitHub и синтетических тестов; новые живые операции — после явного gate.

## 8. Итоговый статус / не выполнено

- **Готово:** нативный HTTPS Connect RPC; real quota read; 4/4 UI agreement; tri-state policy & synthetic Windows CI.
- **Не готово:** identity binding, eligibility flags, session switch, rollback live, in-flight continuity, multi-account quota telemetry, основная Windows host QA 10.1B, GitHub main↔AG_pather merge, Tower production sync.
- **Next:** только CP-54B3; ответ или разработка не должны претендовать на уже выполненную проверку identity.

**Checkpoint authority:** проектный файл по данному пути является владельцем своего курсора. Размещаемые в Башне указатели должны ссылаться на него, не дублировать исполнительное состояние.
