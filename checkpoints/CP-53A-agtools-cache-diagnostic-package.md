# CP-53A — диагностика источника нуля свежих профилей AG-tools

Дата: 2026-10-10. Ветка: AG_pather.
Статус: STATIC_QA_PASS / WINDOWS_PWSH7_RUNTIME_PENDING.

## Зачем
- CP-53 (два запуска) закончился FAILED_SAFELY до любых native writes: 9 RAiF Vault entries, 0 AG-tools cached access tokens, 0/5 test slots, stable verified CP52D rollback.
- В прежнем скрипте любая ошибка чтения JSON, disabled, отсутствие access token или истёкший expiry просто игнорировались. Причина нуля была недиагностируема.
- Пользователь подтвердил, что все девять refresh tokens работают через AG-tools. Отсутствие свежего локального access cache не противоречит этому.

## Изменение процесса
1. Не повторять CP-53 Live вслепую. На скриншоте сейчас выполняется QA Antigravity (main vs AG_pather); не прерывать работающую генерацию.
2. Разделить прочитанные профили на parse_errors, disabled, missing token object, missing refresh/access token, missing expiry, expired/near expiry, fresh.
3. Проверить все уникальные локальные AG-tools data-root candidates: ABV_DATA_DIR, user-home pointer, APPDATA pointer, default user-home directory. Никакие реальные пути не выводить.
4. В Windows CredMan прочитать только RAiF namespace из 9 opaque handles, сравнить refresh значения в памяти без экспорта, вывести только per-root numeric counts matches_any и matches_fresh.
5. Следующий шаг определить автоматизированным безопасным verdict: FIVE_CACHED_FRESH_MATCHES_READY_AFTER_QA / REFRESH_ACCESS_CACHE_IN_AGTOOLS / AGTOOLS_DATA_ROOT_NOT_FOUND / AGTOOLS_PROFILE_FORMAT_NOT_PARSED / PROFILE_LOCATION_OR_REFRESH_MISMATCH.
6. Результат в корень Windows репозитория, полный STEPS.jsonl, RECEIPT.json, STATUS.txt, report.json с агрегатами.
7. Нет OAuth, изменений токенов, изменения native gemini:antigravity, Credential Manager writes, процесса Antigravity, сетевых вызовов или переключения.

## Комплект для пользователя
- ZIP RAiF_AG_CP53A_CacheAudit.zip, SHA256 3739F04B3F9AC0F479A231DB60F10288154772E92F1EDF7BC99C834E1C5BEA37.
- PS1 RAiF_AG_CP53A_Run.ps1, SHA256 57D4BBDAFF2A8171A7B361DE534062DE4FAC6AC58856EAE6F51372FF37F66452.
- PowerShell 7: pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP53A_Run.ps1"
- Result: C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP53A_RESULT_<run-id>.zip
- Script payload: probe.ps1 + README.txt. ZIP CRC pass, script SHA-pinned, allowlisted report.

## Границы
- Статическая проверка без действующего Windows/PowerShell 7; runtime ещё не подтверждён.
- C# native interop читает только RAiF CredMan targets в памяти. Экспортируемые поля — только агрегированные счётчики и диагностические коды, не email/token/account paths.
- Если кэш протух, следующий путь — официальный Refresh All Quotas в AG-tools с локальным обновлением кэша, после завершения текущей QA-задачи; CP53 live только по отдельному решению.
- В публичном GitHub только чекпойнт, исполняемые вложения не публиковать.
- Для живой проверки сохраняется бюджет 60 секунд / 5 аккаунтов, статус hot swap не доказан.

CURSOR: AG_pather / CP-53 NO_CACHED_FRESH_PROFILE → CP-53A READ_ONLY_CACHE_DIAGNOSTIC → CP-53B CACHE_REFRESH_OR_PARSER_FIX → CP-54 CONTROLLED_LIVE_TEST_AFTER_QA.
