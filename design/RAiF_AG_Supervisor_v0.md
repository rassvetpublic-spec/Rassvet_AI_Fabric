# RAiF AG Supervisor — проект с нуля

Дата 2026-10-10. Статус: архитектурный каркас, без исполняемого кода и без runtime проверки.

## Цель
Windows-first управление авторизованными аккаунтами Google Antigravity Standalone и CLI, обнаружение исчерпания квот, восстановление работы локальных задач при переключении аккаунта. Не считать смену Credential Manager бесшовной сменой живого language_server.exe. Не обещать снятие серверных региональных ограничений.

## Подтверждённые исходники и лицензии
- QNIX-Dev/eligibility-antigravity-patcher — Python, MIT; изучать менеджер профилей и отдельные IDE/CLI credential backends.
- demusraph/antigravity-control-center — Python, MIT; изучать Windows Credential Manager, quota telemetry, CDP recovery.
- Muriel-Gasparini/antigravity-account-switcher — Go, MIT; изучать supervisor, 429 detection, replay и ограничения stream lifecycle.
- Doomd/antigravity-account-switcher — JS + PowerShell, MIT; изучать профильный switching + restart fallback.
- AvenCores/open-antigravity-patcher — исторические исходные архивы SourceForge, полный аудит не закончен.
- lbjlaq/Antigravity-Manager — лицензия CC BY-NC-SA 4.0; не копировать в нашу реализацию; пользователь сообщает о несовместимости с AG Standalone.

## Компоненты v0
1. CredentialAdapter: доступ к Windows Credential Manager с минимальными правами; секреты не выводить в logs/checkpoints.
2. AccountRegistry: метаданные профилей (без секретов), статусы и доступность.
3. QuotaMonitor: наблюдение, backoff, детектор 401/403/429, не выполнять слепую ротацию на запреты политики.
4. SessionController: жизненный цикл процесса Standalone/CLI, explicit state machine; проверить live token refresh.
5. TaskCheckpoint: сохранять задание, этап, cursor, безопасный resume; не предполагать возможность replay открытого потока.
6. RecoveryEngine: controlled handoff; при отсутствии hot-swap — согласованный restart+resume с фиксацией потерь.
7. AuditTrail: неизменяемые события, secrets redaction, rollback.

## Безопасность и лицензии
Не копировать исходные фрагменты без аудита и корректных copyright/license notices. Не коммитить токены, cookie, local state.vscdb, Credential Manager dumps. Ротация только между авторизованными профилями, не обходить серверные блокировки. Sandbox tests + backup перед изменением состояния.

## Критерии приемки
A. Проверка standalone version и расположения state/token storage; B. manual switch + valid request; C. auto 429 detection; D. controlled recovery с checkpoint; E. one account failure не заражает остальной пул; F. секреты не попадают в логи; G. no-restart only if proven through live test.

## Следующий курсор
AG_pather / CP-09 SOURCE_AVAILABLE + ARCHITECTURE_DRAFT → CP-10 inspect demusraph / Muriel source modules → CP-11 implement safe skeleton + unit tests → CP-12 Windows sandbox runtime PoC.
