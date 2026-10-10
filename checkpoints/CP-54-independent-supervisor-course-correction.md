# CP-54 — восстановлен независимый план RAiF AG Supervisor

Дата: 2026-10-10. Ветка AG_pather.
Решение пользователя: «мы хотели уйти от AG-tools! у нас столько кандидатов! вспомни план!».

## Исправление ошибки
- Прежний переход к `CP-53B / REFRESH_AGTOOLS_CACHE` отменён: он создавал обязательную runtime-зависимость от AG-tools вопреки исходному плану CP-08.
- CP-53 дважды завершался с 0/5 профилей до изменения credentials; CP-53A подтвердил 9 найденных профилей AG-tools, все 9 expired/near-expiry, 8 совпадений с собственным RAiF Vault. Это не валидация собственной схемы работы RAiF.
- AG-tools исключён из критического пути, источников OAuth и requirement для тестов. Не надо перезапускать приложение только ради актуализации чужого кэша.

## Кандидаты исходной матрицы CP-08
1. demusraph/antigravity-control-center — Windows native credentials, Language Server лог, CDP-контекст; заявленный hot-swap требует отдельного доказательства, потому что switcher в аудитированной версии закрывает приложение.
2. Muriel-Gasparini/antigravity-account-switcher — supervisor, 429 и request replay; Linux-first архитектура, использовать идеи, не зависеть от реализации.
3. QNIX-Dev/eligibility-antigravity-patcher — MIT, credential backends, OAuth/quota; патчер уже использовался в CP-31, не повторять.
4. Doomd/antigravity-account-switcher — restart fallback.
5. AvenCores/open-antigravity-patcher — исходники доступны не полностью, не в runtime-пути.
6. lbjlaq/Antigravity-Manager — AG-tools, сравнительный эталон, не компонент RAiF; CC BY-NC-SA 4.0.

## Готовое к повторному использованию
- Синтетический AccountPool и QuotaAdapter; Windows Vault 9/9; registry + crash recovery; process creation marker + switch verification.
- CP-52D: новый DPAPI CurrentUser native credential snapshot проверен, synthetic CredMan roundtrip успешно выполнен.
- No native login switch yet; genuine hot swap still unproven. User's working Antigravity QA should not be interrupted.

## Документы
- Новый основной execution plan: design/RAiF_AG_Supervisor_Independent_Path_CP54.md.
- design/RAiF_AG_Supervisor_Execution_Plan_CP47.md дополнен пометкой о приоритете нового плана.
- Сохраняются границы docs/PRODUCT_SCOPE.md: без обхода квот потребительских аккаунтов и стороннего неразрешённого API proxy.

## Вектор разработки
- CP-54A: собственный Windows SessionAdapter + исследование CDP/LS/API применимости на Standalone, без AG-tools.
- CP-54B: собственный Auth/Quota adapter из RAiF Vault только при допустимом/поддерживаемом OAuth интерфейсе; при невозможности — user-controlled handoff.
- CP-54C: сначала 2-profile verified switch+restore, затем 5 accounts / <=60s; каждый реальный тест только по явному consent.
- CP-54D: resumable task checkpoint, 401/403 block and 429 backoff; integration CP-55/56.
- Python/PS7 scripts in GitHub public only nonsecret source/tests; user credential material never sent.

## CURSOR
`AG_pather / CP-54 INDEPENDENT_PLAN_RESTORED → CP-54A WINDOWS_SESSION_ADAPTER_PROTOTYPE → CP-54B RAIF_OWNED_AUTH_QUOTA → CP-54C VERIFIED_SWITCH_60S_5_ACCOUNTS`.
