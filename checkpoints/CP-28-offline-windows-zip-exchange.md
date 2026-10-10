# CP-28 — автономный Windows ZIP/PS1 обмен диагностикой

Дата: 2026-10-10
Целевой компьютер: RASSVET_DESKTOP
Статус: пакет подготовлен, **исполнение на машине пользователя ещё не подтверждено**.

## Контракт обмена
- Пользователь помещает два файла в `D:\ЗАГРУЗКИ`: `RAiF_AG_CP28_WinProbe.zip` и `RAiF_AG_CP28_Run.ps1`.
- Запуск: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP28_Run.ps1"`.
- Запускатор проверяет SHA-256 пакета **19325686DA8BA058EF1D6F0B3FF55428D8C6FE3142A6D9DEACAD402D30227577**. При несовпадении ничего из ZIP не выполняется.
- Пакет распаковывается в `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP28_<run-id>\payload`.
- В `_RAIF_RUNTIME` создаётся локальный `.gitignore` со значением `*` для защиты от случайного `git add` результатов.
- Проба выполняется дочерним Windows PowerShell в режиме `-NoProfile -NonInteractive -ExecutionPolicy Bypass`; политики машины глобально не меняются, администратор не нужен.
- Результаты архивируются исключительно из allowlist файлов `report.json`, `SUMMARY.txt`, `STATUS.txt`, `RECEIPT.json`.
- Результат: `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\RAiF_AG_CP28_RESULT_<run-id>.zip`. Пользователь загружает именно его в чат.

## Диагностика
- Версии Windows и PowerShell; наличие команд `git`, `python`, `agy`, `antigravity`.
- Git branch и короткий SHA, флаг изменений отслеживаемых файлов (без имён файлов).
- Имена, PID, время старта и файловые версии только разрешённых процессов: `Antigravity`, `Antigravity IDE`, `language_server`, `agy`. Для `language_server` при доступности SHA-256 бинарника.
- Два снимка процессов с интервалом ~900 мс для наблюдения самопроизвольного рестарта.
- Только булева проверка наличия известного имени записи `gemini:antigravity` в Credential Manager (через `cmdkey /list`); сырой вывод никогда не записывается.
- Проверка существования ограниченного списка известных путей исполняемого файла/SQLite по булевым значениям, без выдачи путей.
- Итоговые флаги `login_identity_verified=false`, `hot_account_swap_verified=false` и `in_flight_task_resume_verified=false`: этот этап не умеет доказывать реальную смену активной сессии.

## Ограничения и защита
- Не читать и не архивировать OAuth access/refresh tokens, cookie, email, экспорт аккаунтов, базы SQLite, журналы, аргументы процессов или память.
- Не завершать процессы, не патчить IDE/CLI, не отправлять сетевые запросы и не запускать облачные модели.
- Выходной ZIP содержит только технические обезличенные сведения. Перед отправкой пользователь может проверить содержимое ZIP.
- Скрипты статически проверены на упаковку, SHA-256 и набор файлов; PowerShell на реальной Windows ещё не запускался, поэтому возможные проблемы совместимости не исключены.
- Исходный ZIP и PS1 распространяются как вложения в чате, **не коммитятся в публичный GitHub**.
- Desktop Commander для RASSVET_DESKTOP был доступен (ping), но месячный лимит удалённых команд исчерпан; этот offline-маршрут заменяет доступ DC.

## Проверка на следующем этапе
1. Получить от пользователя `RAiF_AG_CP28_RESULT_<run-id>.zip`.
2. Проверить `RECEIPT.json`, `report.json` и флаги безопасности; не извлекать секреты.
3. Сопоставить версию Language Server, PID/start, наличие SQLite/Credential Manager и ветку Git.
4. Разработать изолированный контракт активной сессии и план тестирования переключения с checkpoint/resume.
5. Реальный hot swap не считать доказанным до отдельного подтверждения.

## CURSOR
AG_pather / CP-28 PACKAGE_DELIVERED_STATIC_VERIFIED → CP-29 WAIT_FOR_USER_RESULT_ZIP → CP-30 REVIEW_RUNTIME_EVIDENCE.
