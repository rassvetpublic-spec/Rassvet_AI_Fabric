# CP-52C — безопасная диагностика несовпадения DPAPI backup и текущего Credential Manager

Дата: 2026-10-10. Ветка: AG_pather.
Статус: BUILD_COMPLETE / STATIC_QA_PASS / USER_WINDOWS_EXECUTION_PENDING.

## Причина запуска
CP-52B создал локальный DPAPI CurrentUser снимок native target `gemini:antigravity`, но проверка совпадения сразу после создания вернула `ROLLBACK_MISMATCH_CURRENT_NATIVE`. Действующий профиль не менялся. Живой CP-53 блокирован.

## Исследовательский метод без изменений
- PowerShell 7 Windows-only; **read-only**.
- Открывает ровно существующий зашифрованный файл из CP-52B в пределах Windows-профиля, расшифровывает DPAPI CurrentUser в памяти, проверяет схему; файл не перезаписывает и не удаляет.
- Дважды читает нативный `gemini:antigravity` через Win32 `CredReadW` с 120 ms интервалом. Только `CredReadW` и `CredFree` — без `CredWriteW`/`CredDeleteW`.
- Сравнивает сохранённую и текущую записи **без вывода значений**: 8 булевых флагов совпадения (blob, username, comment, alias, flags, type, persist, attribute_count), а также стабильность двух чтений native credentials.
- Verdict: `SNAPSHOT_MATCHES_CURRENT_RESTORE_UNTESTED`, `SNAPSHOT_DIFFERS_FROM_STABLE_NATIVE`, `NATIVE_CHANGED_DURING_AUDIT` либо `BLOCKED_NOT_AUDITED` при ошибке.
- Состояние `SUCCESS` для этого запуска означает лишь успешную **диагностику**. Не означает, что исходный аккаунт восстанавливается или возможен hot swap.
- Запрещены импорт, OAuth, сетевые вызовы, новые DPAPI backup, изменение нативной авторизации, запуск/остановка процессов или модельные ping.

## Артефакты
- `RAiF_AG_CP52C_Diag.zip`: SHA-256 `3F7CB4A8B00EF65ECB9B2A86DB8012860A3D7412BEB6C0F55BBC492BF4B7D03F`; ZIP CRC OK, содержит только `probe.ps1`, `README.txt`.
- `RAiF_AG_CP52C_Run.ps1`: SHA-256 `148D1A853EA8D9B5C77F9E2D0F67C875D477166C80DA0C603DB950100611F8F4`; ASCII, закреплённый SHA-256 ZIP.
- Запуск: `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP52C_Run.ps1"`.
- Итоговый архив: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP52C_RESULT_<runid>.zip`.
- Состав итогового архива ограничен `STATUS.txt`, `SUMMARY.txt`, `RECEIPT.json`, `STEPS.jsonl`, `report.json`. Полный обезличенный журнал всех этапов.
- Пакет доставляется вложениями в чат и не хранится как исполняемое содержимое в публичном GitHub.
- **Нельзя** отправлять encrypted DPAPI backup, user accounts JSON, native credential, email или token: отправлять только итоговый RESULT ZIP.

## Статическая проверка
- ZIP CRC, два ожидаемых файла, pinned SHA-256, ASCII launcher, полный staged logging.
- Разрешены Win32 read/free и DPAPI Unprotect; в payload нет функций сетевого доступа, subprocess kill/restart и credential write/delete.
- Явные output privacy flags: `native_credential_modified=false`, `encrypted_snapshot_modified=false`, `result_secrets_included=false`, `native_restore_executed=false`.
- На настоящем Windows/Pwsh7 этот payload **не проверен**, pass runtime не заявлен.
- GitHub Actions не запускать: только документ, не производственный source CI.

## STOP/GO
Независимо от verdict CP-52C, аварийная команда CP-52B `RestoreNative` остаётся непроверенной. До подготовки валидного механизма восстановления не запускать CP-53; лимит будущего живого испытания 60 секунд / 5 аккаунтов.

## CURSOR
AG_pather / CP-52B MISMATCH → CP-52C RECEIVE_READONLY_DIFF_RESULT → CP-52D REPAIR_CAUSE_AND_RESTORE_GATE → CP-53 OPT_IN_LIVE_60S_5_ACCOUNTS.
