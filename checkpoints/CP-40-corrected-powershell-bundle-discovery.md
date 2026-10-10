# CP-40 — Исправленный Windows preflight ZIP/PS1

Дата: 2026-10-10. Ветка: AG_pather.

## Результат полученного CP-39 ZIP
- Вход: RAiF_AG_CP39_RESULT_20261010_044351_d647d1a8.zip.
- Архив CRC проверен; SHA-256: d59ea91a8a84251ea68c1ca7f62766f33aa65bf8f0fc82297c9cbf04ed9db287.
- Содержит только STATUS.txt, SUMMARY.txt, RECEIPT.json; report.json отсутствует, потому что Python probe не был запущен.
- Статус: FAILED_SAFELY; exit_code=2; reason=BUNDLE_MISSING; source_zip_sha256_verified=false.
- real_credentials_modified=false, antigravity_processes_modified=false (по отчёту запускатора).
- Это ошибка нахождения ZIP и НЕ результат проверки файла аккаунтов, действительности токенов или Language Server.

## Возможные причины
- Исходный архив отсутствует под ожидаемым именем или находится в другой папке.
- В прежнем PS1 был литерал пути с кириллицей D:\ЗАГРУЗКИ; Windows PowerShell 5.1 может читать UTF-8 без BOM как локальную ANSI-кодировку и искажать этот литерал.
- Нельзя доказать, какой из этих факторов был на пользовательской машине, без проверки списка файлов. Новая версия устраняет оба сценария для ZIP, лежащего рядом с PS1, включая браузерное переименование (1).

## Исправленный комплект CP-40
- RAiF_AG_CP40_WinPreflight.zip (2882 bytes), SHA-256 F16FCD706511AEE232B5D63ADA759858216DE0BAF8A670F75B12F718B0567062.
- RAiF_AG_CP40_Run.ps1, SHA-256 6D579307F12BDD344D6A27EE8C4F16751D48B3CF87F5AE0479A8E1466F4EDCDF.
- Только ASCII в исходнике PS1; ZIP ищется относительно $PSScriptRoot (рядом с запускатором), допускаются имена RAiF_AG_CP40_WinPreflight (N).zip; выбирается исключительно архив с закреплённым SHA-256.
- Кириллический путь D:\ЗАГРУЗКИ используется только в команде запуска, но не встроен в исходник PS1.
- Рабочие временные файлы: C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME.
- Итоговый архив: непосредственно C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP40_RESULT_<run-id>.zip.
- Только read-only preflight: локальные процессы, установленные бинарники, присутствие cred targets и проверка структуры JSON in-memory (если локальный файл находится рядом с PS1). Токены, email и SQLite не выгружаются; бинарник не патчится, процессы не перезапускаются.
- Защита от перепутанного ZIP по SHA-256, статус FAILED_SAFELY и отдельный RESULT ZIP даже при ошибках поиска.
- Подтверждено локально: ZIP CRC, hash match PS1, синтетический Python probe exit=0, count=1 и отсутствие тестового секрета в report.json.
- Windows PowerShell 5.1 запуск на RASSVET_DESKTOP ещё не подтверждён; нужен пользовательский RESULT ZIP. Повторное применение патча CP-31 не требуется.
- Пакет передаётся вложениями в чат; не публикуется как исполняемый архив в GitHub.

## CHECKPOINT / CURSOR
AG_pather / CP-40 FAILURE_DIAGNOSED_AND_FIXED_PACKAGE_READY → CP-41 RECEIVE_RAIF_AG_CP40_RESULT_ZIP → CP-42 LOCAL_ACCOUNT_POOL_VALIDATION.
