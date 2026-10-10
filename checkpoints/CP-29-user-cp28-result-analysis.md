# CP-29 — результаты пользовательского Windows CP-28 probe

Дата обработки: 2026-10-10
Вход: RAiF_AG_CP28_RESULT_20261009_232928_a4582abd.zip
Входной SHA-256: d697c730e26d8c424ac0851d7ab0e5cd5238885a48af9874aaadcc260189b66a
Протокол: RAIF_AG_CP28_READONLY, schema_version=1.

## Проверка архива
- ZIP CRC пройден, только RECEIPT.json, report.json, SUMMARY.txt.
- receipt: probe_exit_code=0, sha256_verified=true. Это утверждение самого запускатора, независимое повторное вычисление хеша исходного исполнявшегося ZIP по отчёту невозможно.
- Пользовательский итоговый ZIP не содержит OAuth, email, базы SQLite или дампы, согласно структуре и содержимому проверенных файлов.

## Подтверждённые результаты
- Windows kernel version=10.0.26220.0; Windows PowerShell=5.1.26100.9587.
- Python.exe и py.exe доступны по PATH; git.exe, agy.exe, antigravity.exe не доступны по PATH.
- Найден исполняемый файл в LOCALAPPDATA\\Programs\\Antigravity (presence=true); прочие ограниченные candidate paths не найдены.
- Credential Manager сообщает присутствие target с подстрокой gemini:antigravity. Значения credential не читались.
- Processes before=[], after=[] для allowlist Antigravity, Antigravity IDE, language_server, agy. Значение stable=true в этом случае означает лишь два пустых списка, не доказательство стабильного процесса.
- Git репозиторий скриптом не определён: Git отсутствует в PATH и/или нет .git в RepoRoot; успешный запускатор подтверждает существование C:\\GIT\\Rassvet_AI_Fabric как каталога.
- identity_verified=false, hot_account_swap_verified=false, in_flight_task_resume_verified=false.

## Что неизвестно
- Версия Antigravity.exe и фактическая версия/местонахождение language_server.exe.
- Состояние авторизации и возможность переключения профилей в живой сессии.
- Фактическое место размещения Git.exe; наличие .git внутри workspace.
- Состояние AG Standalone в момент активной работы.

## Следующая проверка
1. Запустить Antigravity Standalone вручную; оставить открытым.
2. Выполнить read-only CP-30 probe, собрать файл, дату и SHA-256 установленного exe / Language Server (если обнаружен), PID+start marker, а также проверить наличие Git по типовым Windows путям без чтения секретов.
3. Обезличенный ZIP прислать для анализа; токены и локальные профили никогда не включать.
4. Не выполнять живой hot-swap до валидации архитектуры и прав доступа.

## CURSOR
AG_pather / CP-29 RECEIVED_VALIDATED → CP-30 LIVE_STANDALONE_SAFE_PROBE → CP-31 PROCESS_AND_VERSION_COMPATIBILITY.
