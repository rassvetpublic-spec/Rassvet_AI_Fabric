# CP-52A — Windows read-only switch capability dry run

Дата: 2026-10-10. Ветка: AG_pather.
Статус: PACKAGE_BUILT_STATICALLY_VERIFIED; RASSVET_DESKTOP_RUNTIME_PENDING.

## Контекст
- Пользователь установил лимит будущего живого теста: 60 секунд суммарно, 5 разных профилей, до 6 контрольных точек с интервалом 10 секунд.
- CP-48–51 подтвердил 9/9 локальных записей в Credential Manager и Registry; AG-tools работоспособность всех 9 профилей подтверждена пользователем, но не повторно проверялась провайдером; live Standalone identity и hot swap пока не подтверждены.
- Исследованные исходники AG-tools различают IDE switch (перезапуск дочернего language_server при сохранении окна) и classic Standalone (полный restart).
- CP-46 Vault хранит только refresh tokens; создание native CredMan credentials для версии Standalone 2.x требует дополнительного материала сессии и контролируемого rollback. Поэтому **не** выполнять небезопасную замену целевого native credential без эксперимента и отдельного согласия.

## CP-52A — что делает
1. Один read-only PowerShell 7 пакет, не вызывает Python.
2. Проверяет валидность локального реестра с opaque identifiers, целостность журнала, наличие 9 CredMan targets; выбирает до пяти candidate slots **по порядку в реестре**, не извлекая токены или email.
3. Проверяет существование native CredMan target (только имя), процессы Antigravity/Language Server, PID и точное UTC-время запуска Language Server, его стабильность на коротком интервале, fingerprint бинарника после CP-31, числовую версию приложения, если доступна.
4. Опционально GET только localhost /health на 127.0.0.1:19527 для AG-tools, timeout 2s; ни /accounts, ни внешних сетевых запросов, ни OAuth.
5. Сохраняет подробный STEPS.jsonl launcher+probe, обезличенный report.json, RECEIPT.json, STATUS.txt, SUMMARY.txt в RESULT ZIP непосредственно в корне проекта.
6. Status SUCCESS означает успешное read-only выполнение. Отдельный capability verdict отражает готовность пяти candidate targets или BLOCKED состояние. **Ни одна реальная смена аккаунта не выполняется**; неизменность PID на коротком интервале не доказывает hot swap.
7. Выходная схема содержит budget 60s/5 accounts и явно помечает live tested=0, provider requests=0, authorization unknown, original session rollback not yet proven.

## Доставка
- ZIP: RAiF_AG_CP52A_WinDryRun.zip, SHA256 854F8EF1A0E997F357F949E6EF0CEE7F99EB6FB9E9D8081D491AA99C3FB277A6.
- PS1: RAiF_AG_CP52A_Run.ps1, SHA256 C81AAE022A509B00F6275CF6541D37C7E1F54CF80FD231CEDB730C1F70C188DA.
- Оба файла отдельно скачиваются в D:\ЗАГРУЗКИ. ZIP вручную не распаковывать.
- Команда: pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP52A_Run.ps1".
- Staging: C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP52A_<runid>.
- Итог: C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP52A_RESULT_<runid>.zip.
- Исходники этой test-delivery не публиковать в GitHub, поставляются вложениями чата. В репозитории только данный не содержащий пользовательских секретов checkpoint.

## Качество и риски
- ZIP CRC, source ZIP sha256 pin in PS1, whitelist ZIP entries, ASCII-only launcher, отсутствие credential read/write, process kill/restart, provider requests и других внешних URL статически проверены в среде сборки.
- PowerShell 7 на реальной Windows **ещё не запускался**; успех нельзя обещать. Если ошибка — только безопасные коды и этапы, без stderr/секретов. Не повторять CP-46 импорт и CP-31 patch.
- Данный запуск не доказывает соответствие RAiF opaque handle активному native аккаунту Standalone. Гейт CP-52B предполагает отдельную доказуемую процедуру возврата к исходной сессии.

## CHECKPOINT → CURSOR
AG_pather / CP-52A ZIP_AND_PS1_READY → CP-52A RECEIVE_RESULT_ZIP → CP-52B RESTORE_SAFE_SWITCH_MECHANISM → CP-53 OPT_IN_LIVE_60S_5ACCOUNTS.
