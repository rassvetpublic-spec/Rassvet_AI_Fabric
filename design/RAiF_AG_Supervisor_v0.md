# RAiF AG Supervisor — проект с нуля

Дата 2026-10-10. Статус: исполняемый прототип и синтетические CI-тесты на Windows готовы; реальная авторизация Standalone и hot-swap не проверены.

## Цель
Windows-only управление авторизованными аккаунтами Google Antigravity Standalone и CLI, обнаружение исчерпания квот, восстановление работы локальных задач при переключении аккаунта. Не считать смену Credential Manager бесшовной сменой живого language_server.exe. Не обещать снятие серверных региональных ограничений.

## Подтверждённые исходники и лицензии
- QNIX-Dev/eligibility-antigravity-patcher — Python, MIT; изучать менеджер профилей и отдельные IDE/CLI credential backends.
- demusraph/antigravity-control-center — Python, MIT; изучать Windows Credential Manager, quota telemetry, CDP recovery.
- Muriel-Gasparini/antigravity-account-switcher — Go, MIT; изучать архитектуру supervisor, 429 detection, replay и ограничения stream lifecycle. Linux-реализация НЕ переносится в продукт.
- Doomd/antigravity-account-switcher — JS + PowerShell, MIT; изучать профильный switching + restart fallback.
- AvenCores/open-antigravity-patcher — исторические исходные архивы SourceForge, полный аудит не закончен.
- lbjlaq/Antigravity-Manager — лицензия CC BY-NC-SA 4.0; не копировать в нашу реализацию; пользователь сообщает о несовместимости с AG Standalone.

## Целевая платформа
- Windows 10/11 x64, Windows Credential Manager, Antigravity Standalone и CLI.
- Linux/macOS runners, упаковка и native adapters не планируются.
- CI — стандартный GitHub-hosted `windows-latest` только для публичного репозитория.
- Синтетические тесты должны проходить без реальных OAuth токенов.

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
AG_pather → CP-27 WINDOWS_ONLY_PUBLIC_CI_VERIFIED → CP-28 LOCAL_AUTH_OBSERVER_DESIGN → CP-29 RASSVET_DESKTOP_RUNTIME_VALIDATION.

## Windows ZIP/PS1 exchange — contract CP-35 (2026-10-10)

- Delivery to user: exactly two files, `RAiF_AG_CPxx_*.zip` plus one `RAiF_AG_CPxx_Run.ps1`, placed in `D:\ЗАГРУЗКИ`.
- One launch line: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CPxx_Run.ps1"`. PowerShell execution-policy bypass only applies to the launched process; do not change machine-wide policy.
- Working root: `C:\GIT\Rassvet_AI_Fabric`.
- **Final result ZIP must be written directly to project root**: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CPxx_RESULT_<timestamp>_<id>.zip`. Avoid `_RAIF_RUNTIME` as final delivery location. Temporary extraction may remain inside `_RAIF_RUNTIME`.
- Root-level `RAiF_*_RESULT_*.zip` and `_RAIF_RUNTIME` excluded by `.gitignore`. This prevents ordinary `git add .` accidents; it does not substitute for checking sensitive content, and `git add -f` can override ignore.
- No real tokens/email/cookies/SQLite credential data or full process command lines in output ZIP. Only a strict allowlist of diagnostic report files, with local ZIP integrity checks and script SHA-256 validation.
- User confirmed Standalone restarted and opened after CP-31 binary patch. CP-34 previously confirmed a model response and quota UI before that restart. Model response **after** restart was not separately reported.
