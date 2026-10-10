# MASTER PLAN — независимый RAiF AG Supervisor (CP-54–56)

**Версия:** 1.0. **Дата:** 2026-10-10. **Ветка:** AG_pather. **Состояние:** план, а не подтверждённый живой switching.

## 0. Главная цель и границы

Разработать Windows-only менеджер **Antigravity Standalone** в составе Rassvet AI Fabric. Он должен самостоятельно учитывать девять уже импортированных профилей, отображать доступность и свежесть разрешённых квот, безопасно наблюдать сессии, выполнять только подтверждённое и разрешённое переключение, сохранять task/cursor и восстанавливаться после прерываний.

**AG-tools не участвует в runtime, авторизации, загрузке access tokens, сопоставлении профилей и тестах.** Путь CP-53B / REFRESH_AGTOOLS_CACHE отменён. AG-tools допустим только как отдельный сравнительный образец UX; не включать его исходники или лицензионные компоненты в RAiF.

Поставщик может запрещать сторонние программные OAuth-потоки, перехват запросов и автоматическую ротацию потребительских аккаунтов ради обхода квот. В соответствии с docs/PRODUCT_SCOPE.md базовая версия предоставляет наблюдение, диагностику, явно санкционированный handoff и recovery. Запрещённая автоматическая ротация в продукт не входит; любой прямой Auth/Quota API adapter проходит самостоятельный compatibility/permission gate.

## 1. Подтверждённый старт: что готово и что нельзя считать доказанным

| Компонент / этап | Подтверждено | Пока неизвестно |
|---|---|---|
| CP-31–35 | рабочий ранее пропатченный Language Server и Standalone, модельные ответы в прежних испытаниях | смена активной авторизации |
| CP-36–37 | собственный AccountPool и строгий parser Gemini/Claude-GPT 5h+weekly | реальный допустимый collector |
| CP-38–48 | RAiF Registry/Vault, 9/9 записей Windows Credential Manager, импорт и recovery journal | срок жизни/OAuth право этих записей для Standalone |
| CP-26/51 | process marker: PID + kernel32.GetProcessTimes FILETIME; verification gate | независимый session identity observer |
| CP-52D | DPAPI CurrentUser v2-snapshot, точный readback native credential, synthetic CredMan create/read/delete | recovery реально авторизованной Standalone сессии после переключения |
| CP-53 | 2 запуска с 0 переключений: зависимость от чужого кэша | ничего о реальной жизнеспособности собственного адаптера |
| CP-53A | чужой кэш: 9 файлов, 9 expired/near-expiry, 8 refresh matches | не блокирует собственный RAiF |
| Issue #1 | конфликт имени теста устранён, Windows CI успешен | ветки main и AG_pather ещё не объединены |

Не повторять импорт девяти профилей, CP-31 binary patch и диагностические CP-52B/C/D. Нынешняя рабочая генерация в Standalone не должна прерываться без отдельного согласия.

## 2. Матрица внешних кандидатов (архитектурные доноры, не runtime)

| Приоритет | Кандидат | Проверяемая идея | Известное ограничение |
|---|---|---|---|
| P0 | demusraph/antigravity-control-center (MIT) | Windows Credential Manager, мониторинг LS, CDP/task resume | анализированный switcher закрывает приложение; безрестартность не доказана |
| P0 | Muriel-Gasparini/antigravity-account-switcher (MIT) | supervisor, bounded 429, lifecycle/replay | Linux-first, не готовый Windows/native Standalone adapter |
| P0 | QNIX-Dev/eligibility-antigravity-patcher (MIT) | WinCred/OAuth schema, разделение IDE/CLI | offline переключение не подтверждает смену работающего LS |
| P1 | Doomd/antigravity-account-switcher (MIT) | Windows controlled restart fallback | полный рестарт |
| P2 | AvenCores/open-antigravity-patcher | исследование исторических бинарных изменений | происхождение полного исходного дерева не подтверждено |
| только справочно | lbjlaq/Antigravity-Manager (CC BY-NC-SA 4.0) | сравнение результата/UX | категорически не зависимость, не копировать код |

Отбор технологии зависит от экспериментального подтверждения на Windows Standalone пользователя, а не README обещаний. Перед использованием конкретного кода — отдельно фиксировать upstream commit, авторство и лицензию.

## 3. Целевая архитектура и контракт

```text
        RAiF CLI / operator-approved task
                     |
           SupervisorCoordinator
             |       |        |
       Registry    Policy    TaskCheckpoint
          |          |        |
     Credential   Quota     Recovery
       Broker    Observer     Engine
           \        |       /
          StandaloneSessionAdapter
         /          |         \
      Observe    Supported   Restart /
                 method       Manual
           \        |        /
             SessionVerifier
             (PID + FILETIME,
              native identity,
              real model evidence,
              task continuity)
                    |
              Redacted Audit
```

**Входы:** opaque registry handles, одноразовое подтверждение оператора, модельная группа, cursor, наблюдаемые показатели. **Выходы:** CapabilityReport, SwitchIntent, SessionEvidence, RestorePlan, SwitchVerdict, разрешённые quota snapshots.

Контракты по файлам:

| Компонент | Предлагаемый файл | Предусмотренные методы |
|---|---|---|
| Native session boundary | src/raif_ag_supervisor/session_adapter.py | inspect, capabilities, prepare, apply_opt_in, observe, rollback |
| Identity evidence | src/raif_ag_supervisor/session_evidence.py | capture, compare_process, attest_identity, verdict |
| Credential scope | src/raif_ag_supervisor/credential_broker.py | list_opaque, exists, acquire_for_authorized_operation |
| Quota telemetry | src/raif_ag_supervisor/quota_observer.py | parse_source, freshness, permitted_poll, invalidation |
| Task continuity | src/raif_ag_supervisor/continuity.py | checkpoint, resume_plan, block_pending_effect |
| Redacted audit | src/raif_ag_supervisor/audit.py | stage, event, safe_error, result_allowlist |
| Windows observer | scripts/ag-supervisor-windows-observer.ps1 | read-only Win32 process/version/capability |
| CLI integration | src/rai_fabric/cli.py | rai supervisor status/capabilities/quotas/plan-switch/recover |

Не делать массового рефакторинга уже готовых core.py, registry.py, pool.py, quota_adapter.py и windows_vault.py. Сейчас WindowsCredentialVault намеренно имеет put/has/delete без публичного dump/get. Для разрешённых операций добавлять узкий in-memory broker с чёткими правами, не экспортировать токены через CLI.

**Состояния:** IDLE → DISCOVERED → CANDIDATE_READY → RESTORE_PREPARED → OPERATOR_APPROVED → APPLYING → OBSERVING → VERIFIED. При недостающих доказательствах: BLOCKED или ROLLBACK_REQUIRED → ROLLBACK_ATTEMPTED → RESTORE_VERIFIED / MANUAL_RECOVERY.

Отдельные факты:

| Факт | Доказательство | НЕ подтверждает |
|---|---|---|
| VAULT_READY | 9 IDs соответствуют 9 Credential Manager targets | действительный OAuth |
| NATIVE_WRITE_OK | native credential readback одинаков | LS использует новый аккаунт |
| CHILD_RESPAWN | тот же UI, новый дочерний LS | hot swap с тем же LS и сохранение потока |
| RESTART_SWITCH_VERIFIED | новая подтверждённая identity и запрос после controlled restart | in-flight continuity |
| HOT_SWAP_VERIFIED | та же пара PID + creation FILETIME, новая независимая identity и продолженный in-flight request | результат без дальнейших ошибок |
| RECOVERY_VERIFIED | исходная native identity, авторизация, рабочая сессия и восстановленный cursor | возможность перепослать необратимый запрос |

Google userinfo нового bearer подтверждает только bearer, но не identity реально активного Standalone. Текст «ping → pong» без независимого model/session evidence — AGENT_TEXT_ONLY.

## 4. Поэтапная реализация

### CP-54A1 — интерфейсы SessionAdapter и synthetic harness

**Сделать:**
- Описать CapabilityReport: OBSERVE_ONLY, OFFICIAL_NATIVE_RELOAD, CHILD_RESPAWN, FULL_RESTART, MANUAL_HANDOFF, UNSUPPORTED.
- Описать SessionSnapshot: pid, process_creation_filetime, native_target_present, app_version, active_identity_attestation (optional), inflight_flag.
- Конечный автомат переключения с запретом apply до restore/consent/permission gates, безопасным fail-closed и одноразовым transaction_id.
- Синтетические tests/test_session_adapter.py, tests/test_session_evidence.py, tests/test_audit.py: отказ при unsupported, stale identity, reused PID, unknown native schema, errors/cancel/concurrency, missing rollback, фальшивый ping.

**PASS:** один пакетный коммит source+tests в AG_pather, **один** Windows CI зелёный. Никаких живых аккаунтов, запросов к Google, Credential Manager writes или процессов.

### CP-54A2–A3 — независимый Windows capability observer и выбор стратегии

**Сделать:** read-only observer на PowerShell 7 проверяет version/build, наличие native target (без credential payload), LS parent/child, PID+FILETIME, опубликованные способы refresh/reload и ограничения UI/CDP. Отдельно проверить, действительно ли Standalone перечитывает credentials без перезапуска — до доказательства статус UNKNOWN. Сопоставить схемы demusraph/ QNIX/ Muriel с фактами, выбрать одну из ветвей OFFICIAL_RELOAD / CONTROLLED_RESTART / MANUAL_HANDOFF / UNSUPPORTED.

**PASS (G1):** техническое RFC с доказательствами способа и ограничениями; один общий Windows read-only RESULT ZIP (если локальное наблюдение требуется), а не последовательность микрозапусков. Если допустимый программный connector отсутствует — немедленно переключиться на user-controlled handoff и task continuity; не писать недокументированный MITM/proxy.

### CP-54B1 — собственный CredentialBroker из RAiF Vault

**Сделать:** использовать только девять opaque ID в RAiF Registry и девять защищённых WinCred records. Реализовать scoped секрет-доступ в памяти локального процесса, журнал only count/status, TTL, блокировку конкурентных транзакций, no disk copies/no HTTP logs. Не устанавливать и не читать AG-tools. Отдельные отрицательные synthetic tests на токены в stdout, logs, exceptions и zip.

**PASS:** девять targets обнаружены без чтения содержимого в публичный отчёт; application без AG-tools работает; 401/403/unknown client не приводят к слепому refresh.

### CP-54B2 — разрешённая авторизация и отдельные квоты

**Сделать:** до какого-либо реального OAuth определить поддерживаемость client flow и право сторонней автоматизации для соответствующей учётной записи. Если не разрешено — PROVIDER_INTERFACE_NOT_PERMITTED (не обходить). Если разрешено — однопрофильный bounded canary, только доверенный endpoint, timeout, no credential redirect, идентичность и срок жизни токена, затем расширять по мере необходимости. QuotaObserver использует только разрешённый источник; 5h и weekly отдельно для Gemini и Claude/GPT, timestamp/reset, запрет optimistic selection при UNKNOWN/stale. Для неподдерживаемой квоты — UNKNOWN, никаких вымышленных процентов.

**PASS (G2):** независимый от AG-tools авторизационный/квотный source проверен с provenance либо честно недоступен; core продолжает работать в read-only режиме. Не пытаться автоматически обходить исчерпанные подписные лимиты.

### CP-54C1 — rollback/handoff harness без пользователя

**Сделать:** synthetic native v2 payloads, fail-before-write, crash-after-write, readback-mismatch, process-death, DPAPI current-user mismatch, transactional one-writer lock, restore marker. Использовать CP-52D snapshot только с проверкой byte-perfect совпадения с текущим native оригиналом. Старый mismatch snapshot CP-52B запретить.

**PASS:** восстановление synthetic состояния и отчётности, утечек нет; byte-perfect DPAPI не выдавать за доказанное восстановление реальной сессии.

### CP-54C2 — первый opt-in live switch: 2 профиля и возврат

**Сделать:** только когда G1/G2 пройдены и текущая задача Standalone завершена. Явный пользовательский запуск: исходный профиль → один кандидат → исходный. На каждой границе фиксировать PID+creation, native readback, независимую Standalone identity, реальный разрешённый model response, самочувствие задачи/cursor. Без positive verification — немедленный rollback, прекращение новых попыток. Если требуется рестарт, результат RESTART_SWITCH_VERIFIED, но НЕ HOT_SWAP_VERIFIED.

**PASS (G3):** обе identity и восстановленная исходная сессия подтверждены. При отсутствии поддерживаемого метода — UNSUPPORTED с рабочей исходной сессией, этап расширения C3 пропускается.

### CP-54C3 — пользовательский лимит 5 аккаунтов / 60 секунд

**Сделать:** только после G3. До 5 различных профилей **включая исходный**, целевой максимум 60 секунд на тестовые действия; до 6 контрольных точек через 10 секунд. Единый запускаемый пакет, не пять скачиваний. Подготовить time reserve для rollback, проверить возможность завершения в пределах бюджета до начала. Если больше нельзя успеть — INCONCLUSIVE_TIMEOUT, остановить новые переключения. В аварийном случае действия по восстановлению исходного состояния могут выйти за 60 секунд, но эксперимент не продолжается: отдельно отмечать RECOVERY_OVERRUN.

**PASS (G4):** либо полные 5/5 с подтверждёнными состояниями, либо структурированный безопасный частичный результат. Нельзя назвать PASS при 5 успешных credential readbacks и нуле модельных identity evidence.

### CP-54D — task checkpoint, recovery и события

**Сделать:** checkpoint сохраняет task_id, repo/ref/sha, workspace, cursor, generation/lease, last side-effect/idempotency state. После прерывания неизвестный побочный эффект = BLOCKED_PENDING_REVIEW, не повторять слепо commit/PR/email. CDP подход demusraph — отдельный research gate; сохранённое окно ≠ продолженный поток. Synthetic fault injection: 401/403, 429 cooldown, stale quota, lost connection, child respawn, full restart, revoked profile, parallel transaction, crash during rollback.

**PASS (G5):** восстановление task/cursor без двойных необратимых действий, с раздельными flags UI_SURVIVED/LS_RESPAWNED/TASK_RESUMED/STREAM_CONTINUED.

### CP-55 — интеграция с Fabric

**Сделать:** CLI rai supervisor, read-only status/quotas/capabilities, gated plan-switch/recover. Связать Task Graph, Workspace Registry, CKS read-only, RulesHub/Control Tower authority readback. Log event provenance: git SHA, binary fingerprint, script checksum, result checksum и status. Dashboard показывает фактическую readiness, freshness и blocking reasons.

**PASS (G6):** проверенные интеграционные контракты и Mock E2E, без прямой записи в CKS Canon и неразрешённых действий.

### CP-56 — Windows release и слияние

**Сделать:** тесты cold-start/reboot, Standalone update, revoked credentials, interrupted task, DPAPI mismatch, offline/network timeout, WindowsApps python alias. Проверить лицензионный provenance, отсутствие секретов, operator runbook. Issue #1: устранение названного add/add уже в AG_pather, но полная merge QA main↔AG_pather ещё требуется; не делать слепой merge.

**PASS (G7):** продукт работает без AG-tools, Windows-only CI зелёный, live и recovery результаты воспроизводимы либо функциональное ограничение явно описано.

## 5. Тестовая стратегия и экономия Windows/GitHub CI

| Уровень | Место | Сколько раз |
|---|---|---|
| Offline state/protocol/unit | GitHub windows-latest, synthetic | одна пачка на завершённый кодовый этап, а не один запуск на модуль |
| Native WinCred synthetic canary | Windows PowerShell 7 | только при изменении Win32 границы |
| Read-only capability | RASSVET_DESKTOP, один ZIP+PS1 | один объединённый пакет CP-54A2/A3 |
| Controlled 2-profile | Windows Standalone, явно разрешённая операция | один тест после G1/G2 |
| Timed 5-profile | Windows Standalone | один тест после 2-profile PASS |
| Crash/resume | synthetic + один осторожный Windows тест | CP-54D |
| End-to-end Fabric | Windows CI + operator acceptance | CP-55/56 |

Никаких Linux/macOS runners. CI использует стандартный hosted Windows job публичного GitHub репозитория, без секретов, без запуска реальных provider APIs, без larger runners. Документационные коммиты не инициируют CI.

**Локальный обмен:** ZIP + один PS1 в D:\ЗАГРУЗКИ; одна команда pwsh.exe, staging в _RAIF_RUNTIME; результат RAiF_AG_CPnn_RESULT_<runid>.zip прямо в C:\GIT\Rassvet_AI_Fabric. Не рассчитывать без проверки, что в локальной папке проекта присутствует .git.

## 6. Схема безопасного лога

STEPS.jsonl: utc, monotonic_elapsed_ms, component, stage, state, safe_error_code, evidence_level. RECEIPT.json: protocol, mode, status, bundle_sha256_verified, exit_code, completed_stage. report.json: aggregated counts, gates and verdicts, PID+creation, restore flags.

Запрет в результатах: refresh/access/id tokens, credential blobs, email, личные пути, full command line, исходный JSON, DPAPI binary и сырые провайдерские HTTP ответы. Использовать slot 1..5 вместо email/opaque handle. Каждое изменение реального native credential фиксировать до действия в несекретном rollback journal; no persisted plaintext.

## 7. Gates и риск-контроль

| Gate | Условие PASS | При FAIL |
|---|---|---|
| G0 | зафиксирована текущая готовая база, никакого повторного импорта/патча | только read-only диагностика |
| G1 | подтверждён разрешённый способ взаимодействия со Standalone | MANUAL_HANDOFF_ONLY или UNSUPPORTED |
| G2 | допустимый credential/quota source, не связанный с AG-tools | UNKNOWN/PROVIDER_INTERFACE_NOT_PERMITTED |
| G3 | 2-account switch и фактический возврат исходной авторизации | не запускать 5-profile тест |
| G4 | 5/5 в 60 секунд с полноценными evidence либо корректный partial | INCONCLUSIVE_TIMEOUT/IDENTITY |
| G5 | checkpoint/resume без duplicate side effects | BLOCKED_PENDING_REVIEW |
| G6 | authority gates и Fabric interface проходят E2E | запрет публикации в нормативные домены |
| G7 | Windows CI, privacy/security QA, runbook, merge review | релиз заблокирован |

**Основные риски:** наличие токена ≠ новая сессия LS; сохранённое окно ≠ сохранённая генерация; смена PID может быть незаметна без FILETIME; DPAPI сохранение ≠ фактическое recovery; создание запрещённого стороннего proxy не допускается; автоматическая ротация ради обхода лимитов исключена; пользовательская QA-работа важнее эксперимента.

## 8. Приоритетный backlog файлов

| Priority | Файл | Основной артефакт |
|---|---|---|
| P0 | src/raif_ag_supervisor/session_adapter.py | интерфейс, capability enum и state machine |
| P0 | src/raif_ag_supervisor/session_evidence.py | evidence и проверка реальной identity |
| P0 | src/raif_ag_supervisor/audit.py | privacy-safe event/receipt schema |
| P0 | tests/test_session_adapter.py | table-driven synthetic transitions |
| P0 | tests/test_session_evidence.py | отрицательные PID/identity/stream сценарии |
| P0 | tests/test_audit.py | антиутечки и fail-stage tests |
| P1 | scripts/ag-supervisor-windows-observer.ps1 | read-only Windows capability |
| P1 | src/raif_ag_supervisor/credential_broker.py | ограниченное получение секрета in-memory |
| P1 | src/raif_ag_supervisor/quota_observer.py | разрешённые quota sources и freshness |
| P2 | src/raif_ag_supervisor/continuity.py | durable cursor, idempotency, resume |
| P2 | src/rai_fabric/cli.py | facade команд supervisor |

Не добавлять чужие исполняемые файлы, linux dependencies и AG-tools specific paths.

## 9. Следующее действие и контрольный курсор

**CP-54A1:** реализовать интерфейсы session_adapter.py, session_evidence.py, audit.py и синтетические тесты; один кодовый коммит в AG_pather и один Windows CI. Это можно сделать полностью офлайн, не мешая работающему Antigravity.

**CURSOR:** AG_pather → CP-54A1 OWNED_SESSION_ADAPTER_CONTRACT_AND_TESTS → CP-54A2 WINDOWS_READONLY_CAPABILITY → G1 → CP-54B OWNED_AUTH_QUOTA → G2 → CP-54C 2_PROFILE_THEN_5_IN_60S → CP-54D CONTINUITY → CP-55/56.

## 10. Основания

- design/RAiF_AG_Supervisor_v0.md
- design/RAiF_AG_Supervisor_Independent_Path_CP54.md
- design/RAiF_AG_Supervisor_Execution_Plan_CP47.md
- checkpoints/2026-10-10-antigravity-patcher-audit.md (матрица CP-08 и исходники CP-10/11)
- checkpoints/CP-53A-and-issue-1-triage.md
- docs/PRODUCT_SCOPE.md

Конкретные функции, сроки и сторонние API, для которых нет оснований в этих документах, обозначены выше как **предлагаемая архитектура**, а не подтверждённые возможности.

## 11. Решение после статического аудита реального language_server.exe (2026-10-10)

Подробный подтверждённый разбор: [CP-54A-native-language-server-rpc-binary-findings.md](CP-54A-native-language-server-rpc-binary-findings.md).

**Приоритет MASTER PLAN изменён:** не разрабатывать тяжёлый `SessionAdapter` и новый Google OAuth Manager до проверки встроенного интерфейса. Пропатченный действующий Windows LS (SHA-256 `b23c730a3b23953a7e46851593a5013bc888c524c8965cbb21618fc51122d81e`) содержит protobuf `LanguageServerService` с 324 методами и `HostBridgeService` с `GetOAuthToken`.

Встроенные `GetAuthStatus`, `HasAuthToken`, `GetUserStatus`, `GetAvailableModels`, `RetrieveUserQuotaSummary` и OAuth state stream допускают исследование собственного минимального **read-only ConnectRPC observer** вместо повторения их функциональности в отдельном сервисе. В схеме `LoginRequest` нет поля передачи готового token; среди 324 RPC не выявлены точные `SwitchAccount`/`SetAuthToken`/`ReloadCredentials`. Поэтому возможность бесшовного переключения 9 аккаунтов **не подтверждена**.

**Новый ближайший курсор:** `CP-54A1 / READ_ONLY_LIVE_LOCAL_RPC_PROBE → CP-54A2 / MINIMAL_CONNECT_CLIENT_IF_SUPPORTED → CP-54B / SUPPORTED_SESSION_RELOAD_PROOF → CP-54C / SAFE_TWO_THEN_FIVE_PROFILE_TEST`.

Если локальный протокол не разрешён для сторонней программной автоматизации или сервер не предоставляет подходящий метод смены авторизации, RAiF остаётся независимым в статусе/квотах/задачах и применяет user-controlled handoff с checkpoint. Не перепатчивать LS и не воспроизводить неизвестный auth protocol.
