# CP-42 — Полное пошаговое логирование, PowerShell 7 без Python

Дата: 2026-10-10
Ветка: AG_pather

## Разбор CP-41
- Получен `RAiF_AG_CP41_RESULT_20261010_045438_85e8d2fe.zip`.
- ZIP CRC: OK. Содержимое: `STATUS.txt`, `SUMMARY.txt`, `RECEIPT.json`; `report.json` отсутствует.
- RECEIPT: `status=FAILED_SAFELY`, `reason=READONLY_PROBE_FAILED`, `failed_or_completed_stage=invoke_probe`, `python_exit_code=9009`, `powershell_version_major=7`, `source_zip_sha256_verified=true`.
- Код 9009 типичен для неработающего Python/App Execution Alias, но конкретная причина без вывода дочернего процесса не доказана.

## Исправление CP-42
- Полностью исключён Python как runtime-зависимость. Новый probe написан для PowerShell 7 и запускается напрямую из PS1.
- Пошаговое структурированное логирование launcher + probe: `STEPS.jsonl` с ограниченными полями `utc, component, stage, state, code, elapsed_ms` (без исключений, путей, email и OAuth).
- Этапы launcher: версия PS7, существование проекта, подготовка runtime, поиск архива, сверка SHA-256, извлечение, выбор необязательного JSON, запуск probe, проверка отчёта, формирование квитанции, упаковка результатов.
- Этапы probe: платформа, Git и проект, процессы по allowlist, установленный Language Server (только размер/хеш/версия), только наличие credential targets, структура локального JSON (только статус и количество), метаданные реестра (только количество), сериализация отчёта.
- Все промежуточные события до создания runtime буферизуются и добавляются в `STEPS.jsonl`. В конце archive build выполняется дважды, чтобы лог успешной упаковки вошёл в итоговый ZIP.
- Ошибки этапов дают только безопасные коды и типы исключений, stderr и значения секретов не пишутся.
- ZIP архив и PS1 передаются в ChatGPT как два файла, НЕ записываются в публичный репозиторий.
- Распаковка в `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP42_<id>`; результирующий `RAiF_AG_CP42_RESULT_<id>.zip` сохраняется непосредственно в корне проекта.
- Источник ZIP выбирается рядом с PS1 по имени `RAiF_AG_CP42_WinProbe.zip` с поддержкой суффиксов `(1)`, `(2)` и сверкой закреплённого SHA-256.
- Пакет: `RAiF_AG_CP42_WinProbe.zip`, SHA-256 `C3914A981A4BD0D6B954C5B78CB557E5A406D7F2008CD03DB150D30D7139E25C`.
- Запускатор: `RAiF_AG_CP42_Run.ps1`, SHA-256 `7B46947FF76983F19C9C792F4A345DA9F1E8552D9359D734FFDC43CE8CE95810`.
- Команда: `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP42_Run.ps1"`.

## Проверки и границы
- Проверено в среде подготовки: ZIP CRC, совпадение закреплённого SHA, состав только двух безопасных файлов ZIP, ASCII-кодировка PS1, присутствие всех заявленных стадий и запрет сетевых запросов/изменения credential state.
- PowerShell 7 недоступен в среде сборки: сам PS1 на Windows ещё **не исполнен и не признан runtime-validated**.
- Никакие пользовательские OAuth-токены, email или JSON-профили не загружались в GitHub или CI.
- Программа только читает разрешённые сведения и проверяет формат локального файла аккаунтов, если он есть рядом с запускатором; не переключает аккаунты, не перепатчивает бинарник, не запускает модели.
- Предложение подключить Antigravity для семантического анализа пока не требуется: устранена конкретная проблема зависимости от Python.

## CURSOR
AG_pather / CP-42 BUILT_STATICALLY_VERIFIED → CP-43 RECEIVE_PWSH7_STAGE_LOG_RESULT → CP-44 ACCOUNT_POOL_LOCAL_VALIDATION.
