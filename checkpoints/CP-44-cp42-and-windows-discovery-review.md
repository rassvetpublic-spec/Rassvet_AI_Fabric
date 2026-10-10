# CP-44 — проверка двух диагностических ZIP: CP-42 и Windows Discovery

Дата: 2026-10-10
Ветка: AG_pather
Статус: TWO_ARCHIVES_VERIFIED / ACCOUNT_MANIFEST_NOT_FOUND

## Целостность
- `RAiF_AG_CP42_RESULT_20261010_050605_24b1e78f.zip`: SHA-256 `510da4280899d23f3609b0d2fab3d29ab6cea479455006e34ba0a7ab561f6240`; ZIP CRC OK, ровно 5 разрешённых файлов.
- `RAiF-Windows-RESULT-DISCOVERY-20261010_050348_18c895c7.zip`: SHA-256 `17be128ea6edc2adf31a8d8b6110857448e23d715d1f2e7506c6a71a5c3d9520`; ZIP CRC OK, 9 диагностических файлов.
- Оригинальные пользовательские ZIP/логи не коммитились; никакие secrets, имена аккаунтов, абсолютные пользовательские пути или полные командные строки процессов не публикуются.

## CP-42 итог
- `RAIF_AG_CP42_PWSH7_READONLY`, receipt status SUCCESS, reason NONE, exit_code 0, probe_exit_code 0, ZIP SHA verified.
- STEPS.jsonl: 40 событий, 19 start + 21 ok, ошибок нет.
- Windows; PowerShell 7; бинарник language_server.exe существует, размер 165675008; SHA-256 `b23c730a3b23953a7e46851593a5013bc888c524c8965cbb21618fc51122d81e` совпадает с CP-33 (после патча).
- На момент съёма: 6 процессов Antigravity и 1 language_server. Нативный credential target Antigravity обнаружен, isolated RAiF targets = 0.
- Локальный реестр RAiF отсутствует, pending recovery false. Отправка сетевых запросов, изменение токенов, процессов и переключение аккаунта не выполнялись.
- `accounts_file.present=false`, `valid_format=null`, `accounts=null`. Это НЕ проверка валидности JSON и НЕ свидетельство проблемы с refresh tokens.
- Проверен исходный CP-42 PS1: без `-AccountsJson` ищет файл ТОЛЬКО в каталоге самого Run.ps1, с ТОЧНЫМ именем `antigravity_accounts_2026-09-14.json`. Шаг `select_account_file` помечает ok даже если файл отсутствует; реальное отсутствие отражено в report.json.

## Windows Discovery отдельно от CP-42
- `RAI_FABRIC_WINDOWS_PROVIDER_RESULT/2`: verdict PASS, scanner PASS; 11 этапов, без сообщённых error_types.
- PowerShell 7.6.6; Antigravity 2.22.0; Antigravity Tools 4.9.7-beta.4; обнаружен OpenAI Codex Desktop.
- Диагностировано 300 процессов: 26 подходящих по критериям Codex и 7 Antigravity; эти числа не равны количеству независимых AI сессий.
- Git `2.55.0.windows.5` отмечен как доступный через winget, при этом CP-42 `git_on_path=false` и `git_metadata_present=false` в проверенном каталоге. Никакого противоречия в содержании двух отдельных проверок: установка Git не гарантирует его наличие в PATH и не создаёт .git.
- Discovery сообщает `auth_files_read=false`, `model_calls=0`, `oauth_requests=0`. Информация только со слов отчёта, не независимый аудит всех процессов пользователя.

## Решение
1. Сначала обеспечить локальное наличие экспортированного JSON. Вариант без новой сборки: поместить файл под точным именем `antigravity_accounts_2026-09-14.json` рядом с `RAiF_AG_CP42_Run.ps1`; либо передать `-AccountsJson` с реальным локальным путём.
2. Повторить CP-42 только если нужна проверка формата. Не загружать сам JSON с refresh tokens, только новый RESULT ZIP.
3. Не изменять действующую авторизацию Standalone и не перепатчивать Language Server.
4. Импорт в RAiF vault остаётся отдельной явно подтверждаемой операцией. Hot swap не доказан.

## CURSOR
AG_pather / CP-44 REPORTS_VALIDATED + FILE_LOCATION_BLOCKER → CP-45 LOCAL_MANIFEST_PREVIEW → CP-46 ISOLATED_WINDOWS_IMPORT_BY_CONSENT → CP-47 STANDALONE_SESSION_SWITCH_PROBE.
