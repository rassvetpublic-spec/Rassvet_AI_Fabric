# RAiF AG Supervisor — независимый путь после CP-53A

Дата: 2026-10-10. Ветка: `AG_pather`.
**Статус: решение об архитектуре.**
**Цель:** собственный Windows-only менеджер разрешённых профилей **Antigravity Standalone**. Ни установленный AG-tools, ни его файлы/кэш/API не требуются в рабочем контуре.

## Исправление курса

Переход `CP-53B / REFRESH_AGTOOLS_CACHE` признан **ошибочным** и отменён.
CP-53 использовал кэш AG-tools как обязательный source of access tokens и завершился дважды `FEWER_THAN_FIVE_FRESH_MATCHES` без единого переключения. CP-53A подтвердил: 9 профилей AG-tools, все 9 access tokens истекли/скоро истекают, совпадение по refresh token с отдельным RAiF Vault — 8/9. Это отражает только состояние кэша AG-tools, **не** работоспособность RAiF Vault.
Пользователь подтверждает 9/9 работающих аккаунтов через AG-tools и отдельно требует уйти от AG-tools.

Историческая база: `checkpoints/2026-10-10-antigravity-patcher-audit.md` (CP-07, CP-08, CP-10/11), `design/RAiF_AG_Supervisor_v0.md`, `design/RAiF_AG_Supervisor_Execution_Plan_CP47.md`, `design/CP-52-controlled-standalone-switch.md`.

## Проверенные кандидаты — только технологические доноры

| Кандидат | Применимая идея | Ограничение |
|---|---|---|
| `demusraph/antigravity-control-center` — MIT | Windows Credential Manager, опрос `language_server`, CDP-контекст и продолжение задачи | Анализированный switcher содержит принудительное закрытие Antigravity; «без рестарта» исходниками не доказано |
| `Muriel-Gasparini/antigravity-account-switcher` — MIT | Supervisor/loopback relay, 429 state machine, request replay и sticky routing | Linux-first; не является готовым Windows-native Standalone adapter; нельзя прозрачно вмешиваться в неподдерживаемый сетевой протокол |
| `QNIX-Dev/eligibility-antigravity-patcher` — MIT | Credential Manager/SQLite раздельно, токен-схемы, OAuth/quota primitives | Offline profile switch требует restart; патчер CP-31 уже применён, повторять не надо |
| `Doomd/antigravity-account-switcher` — MIT | Restart+resume fallback и скрипты Windows | Не решает бесшовную смену |
| `AvenCores/open-antigravity-patcher` | Исторические версии binary patch | Источник GitHub недоступен, полный аудит не завершён; не ставить в критический путь |
| `lbjlaq/Antigravity-Manager` (AG-tools), CC BY-NC-SA 4.0 | Только эталон UX и сравнение результатов | **Не SDK, не runtime-зависимость, не источник обязательного fresh access token**, не копировать код |

## Уже готовое, без повторения тестов

- CP-31/33: известная версия `language_server.exe` уже патчена и рабочая. Новых бинарных патчей не делать.
- CP-36/37: `raif_ag_supervisor.pool` и `quota_adapter` — синтетическая логика 429 и 5h/weekly quotas без реального provider adapter.
- CP-46/48: 9 записей в **собственном** Credential Manager namespace `RAiF_AG_Supervisor:account:...`; структурный реестр `accounts.json`, crash journal; импорт повторять не надо.
- CP-26: `session_probe.py` уже содержит Windows `GetProcessTimes`, а `verification.py` требует `PID+creation-time`, новую подтверждённую identity и реальную continuity. **Hot swap не доказан**.
- CP-52D: нативный `gemini:antigravity` успешно сохранён в локальном DPAPI CurrentUser v2 snapshot, проверен byte-perfect roundtrip; synthetic CredWrite/Read/Delete прошёл; восстановление живой сессии ещё не испытано.
- CP-53A: проблема свежего кэша AG-tools найдена, но **не блокирует альтернативную независимую архитектуру**.

## Новый план — последовательные технические контрольные точки

### CP-54A / OWNED_WINDOWS_ADAPTER_DESIGN (следующий)

- Спроектировать интерфейсы `RaifCredentialProvider`, `StandaloneSessionAdapter`, `TaskContinuityObserver`, `QuotaObserver`.
- Источник аккаунтов — **только RaIF Registry + Vault**. AG-tools не устанавливать, не читать и не обновлять.
- Local-only read-only discovery: как Standalone загружает native v2 credential, когда LS кэширует данные, можно ли подтвердить identity и обеспечить reload без завершения задачи. Изучить Windows/CDP-донор demusraph и protocol relay Muriel, но не копировать чужие реализации.
- Явно различать status `NATIVE_RELOAD_SUPPORTED`, `RESTART_REQUIRED`, `UNSUPPORTED`, `UNVERIFIED`.

### CP-54B / RAIF_OWNED_AUTH_AND_QUOTA

- Проверить доступность **разрешённого** способа получения/обновления access tokens из локального Vault по конкретным OAuth-клиентам, строго на Windows, без зависимости от AG-tools.
- Не предполагать, что refresh_token сам по себе достаточен для native v2 profile. Отдельно доказать token refresh, TTL и идентичность выбранного профиля. Все секреты только в памяти, structured safe codes.
- При отсутствии поддерживаемого/разрешённого способа — не подменять официальную авторизацию и не строить несанкционированный proxy; использовать официальное переключение в интерфейсе или сценарий ручного handoff.
- `QuotaObserver`: действительные 5h/weekly для Gemini и Claude/GPT по доступному разрешённому интерфейсу, не придумывать проценты.

### CP-54C / NATIVE_SESSION_SWITCH_PROOF

- Только после полного rollback gate — opt-in переключить сначала исходный + один альтернативный профиль, проверить независимую **реальную Standalone identity и модельный ответ**, затем **вернуть исходный профиль**.
- Если способа без рестарта нет, фиксировать `RESTART_REQUIRED` и проверять controlled restart+checkpoint/resume, а не выдавать это за hot swap.
- Расширение до **пяти разных аккаунтов суммарно за не более 60 секунд** — только при прохождении 2-profile gate. Шесть контрольных точек по 10 секунд, полный стадийный журнал, при невозможности выполнить за минуту — `INCONCLUSIVE_TIMEOUT`.
- Не прерывать уже выполняемую QA-генерацию по собственной инициативе.

### CP-54D / RECOVERY_AND_TASK_CONTINUITY

- Изучить CDP-approach demusraph и контроль checkpoint/cursor в Fabric; восстановление задачи по подтверждённому cursor.
- Replay потока/HTTP-запроса не эквивалентно сохранению уже начатой генерации. При неподдерживаемом replay не дублировать необратимые операции.
- Изолированные ошибки 401/403 не должны приводить к автоматической смене; 429 обрабатывать только в рамках разрешённых провайдером сценариев. Исполнение не должно обходить серверные лимиты/политики.

### CP-55/56 / INTEGRATION_AND_RELEASE

- Отдельный Windows Control Tower / CKS / RulesHub contract и набор интеграционных тестов.
- Windows hosted CI, RASSVET_DESKTOP opt-in runtime test, обновление приложения, аварийное восстановление, redacted audit.
- Целевая программа — полностью функциональна без AG-tools.

## Обязательные границы из PRODUCT_SCOPE.md

Проект Fabric не допускает автоматического обхода лимитов потребительских аккаунтов через сторонний worker/proxy. Доступные методы интеграции Antigravity/Google должны соответствовать условиям поставщика. Там, где разрешён только самостоятельный интерфейс IDE/CLI, реализовывать read-only наблюдение и управляемый пользователем handoff, а не молчаливое использование OAuth в стороннем API.

## Контракт тестового обмена

PowerShell 7 Windows-only. `D:\ЗАГРУЗКИ`: один ZIP + один PS1, одна команда. Итоговый `RAiF_AG_CPnn_RESULT_*.zip` строго в корне `C:\GIT\Rassvet_AI_Fabric`. Полный `STEPS.jsonl`, `RECEIPT.json`, `STATUS.txt`, обезличенный `report.json`. В GitHub — только не секретные исходники, тесты и checkpoint.

## CHECKPOINT / CURSOR

`AG_pather → CP-54A / INDEPENDENT_WINDOWS_SESSION_ADAPTER → CP-54B / OWNED_AUTH_QUOTA → CP-54C / NATIVE_SWITCH_PROOF → CP-54D / CONTINUITY → CP-55/56`.

**Запрещённый старый курсор:** `CP-53B / REFRESH_AGTOOLS_CACHE` как обязательный шаг.
