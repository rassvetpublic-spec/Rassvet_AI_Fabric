# AG_pather — аудит патчеров Antigravity

Дата: 2026-10-10. Статус: частичная статическая проверка, патчи не запускались.

## CP-01 — GitHub и идентичность
- Целевой репозиторий: rassvetpublic-spec/Rassvet_AI_Fabric; ветка AG_pather создана от main (95122c90a4ac684e0ffba8b493001f7c4797d15a).
- QNIX-Dev/eligibility-antigravity-patcher доступен. Основной файл manager.py, blob SHA 544b1aa3e438804b02aa32bb395544cc6f2493ef. Лицензия MIT. На момент проверки: 114 stars, 16 forks, 2 open issues.
- AvenCores/open-antigravity-patcher: GitHub REST 404. Есть сторонние репозитории с похожими именами, авторство/происхождение не подтверждено. Сравнительная репутация AvenCores не проверена.

## CP-02 — частичный аудит manager.py
- Код использует Windows Credential Manager (ctypes) и SQLite state.vscdb; snapshot CLI/Manager сериализует учётные данные в Base64. Base64 НЕ шифрование. Источник: manager.py, строки 701–816.
- OAuth refresh: POST https://oauth2.googleapis.com/token, квоты POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary. Источник: manager.py, строки 960–1065.
- В просмотренном модуле network: фиксированные Google endpoints, блокирование редиректов с bearer/OAuth headers, HTTP timeout 15 сек, лимит ответа 1 MiB. Признаков отправки токена произвольному домену в этом модуле не найдено. Это не доказательство безопасности всего репозитория.
- Бинарный патчер содержит сигнатуры hasValidAuth для x64/arm64, резервные копии .agybak; источник: manager.py, строки 576–600 и константа BAK.
- Прямую поддержку AG-tools (отдельного продукта) и совместимость с установленной версией НЕ подтвердили.

## CP-03 — предварительный вердикт
- QNIX: опасность сохранения и переключения refresh tokens; защищать резервные копии и профили, не запускать с повышенными правами без необходимости.
- AvenCores: исходный оригинальный репозиторий недоступен по ранее данному URL; прежняя оценка его репутации отозвана до идентификации оригинала.
- Оба патчера не запускались; динамического анализа, проверки сетевого поведения процесса и анализа подписей нет.

## CURSOR
AG_pather / CP-03 complete → CP-04 provenance AvenCores → CP-05 full static diff → CP-06 AG-tools integration compatibility.

## TOKEN USAGE
Точный расход токенов модели за разговор и обращения к инструментам недоступен. Числовая оценка не выдаётся за фактический биллинг.


## CP-04 — веб-поиск происхождения AvenCores (2026-10-10)
- В поисковой выдаче индексируются исходные GitHub-страницы https://github.com/AvenCores/open-antigravity-patcher/issues, /pulls, /actions и /discussions. Но прямой GitHub API для репозитория возвращает 404; доступность исходников на GitHub сегодня НЕ подтверждена.
- SourceForge: https://sourceforge.net/projects/open-antigravity-patcher/files/; архивы от avencores, в том числе V1.1.1 (2026-05-06), V1.2.4 (2026-07-15), V1.3.2 (2026-08-04), V1.3.5 (2026-09-02).
- V1.3.5 сообщает об атомарной замене и валидации патчей для POSIX; V1.3.2 атрибутирует патч ARM64 для Antigravity 2.5.0 проекту QNIX-Dev/eligibility-antigravity-patcher.
- Имеются ссылки на GitHub Actions, VirusTotal и исходные архивы; содержимое архивов и результаты сканирования не проверены.
- Вывод: историческое происхождение AvenCores подтверждается несколькими страницами и архивами, но безопасность и текущая поддержка не доказаны.

Источники:
- https://github.com/AvenCores/open-antigravity-patcher/issues
- https://github.com/AvenCores/open-antigravity-patcher/pulls
- https://sourceforge.net/projects/open-antigravity-patcher/files/V1.3.2/
- https://sourceforge.net/projects/open-antigravity-patcher/files/V1.3.5/

## CURSOR (обновлено)
AG_pather / CP-04 COMPLETE → CP-05 full static audit → CP-06 AG-tools compatibility.


## CP-05 — свежесть и границы статического аудита (2026-10-10)
- SourceForge подтверждает V1.3.8 (2026-09-21) как самый новый из видимых выпусков. Источник: https://sourceforge.net/projects/open-antigravity-patcher/files/V1.3.8/
- V1.3.8: архивы исходников ZIP 155.4 KB и TAR.GZ 141.9 KB; Windows x64/ARM64, Linux x64/ARM64, macOS; заявлен ARM64 патч для AGY CLI 1.2.7.
- GitHub Actions release: https://github.com/AvenCores/open-antigravity-patcher/actions/runs/35653528572; VirusTotal ссылки размещены в SourceForge release notes. Содержимое проверок не инспектировалось.
- Наблюдаемый GitHub исходный файл (индекс): https://github.com/AvenCores/open-antigravity-patcher/blob/main/source/patcher/manager/patcher.py (454 lines); прямое получение страницы даёт 404.
- Попытка скачать архив V1.3.8 в среду аудита не удалась: DNS для downloads.sourceforge.net отсутствует. Поэтому полного исходного анализа AvenCores нет; уверенный вывод о безопасности/сетевой активности делать нельзя.
- QNIX: ранее проверенные manager.py сетевые вызовы OAuth и quota, работа с refresh_token, credential manager, база SQLite и сигнатуры патча остаются действительными только для проверенной версии файла blob 544b1aa3e438804b02aa32bb395544cc6f2493ef.
- Совместимость отдельного AG-tools НЕ подтверждена ни функциональным тестом, ни анализом конкретной версии.

CURSOR: AG_pather / CP-05 PARTIAL (blocked source retrieval) → CP-06 AG-tools identification → CP-07 runtime validation (safe test environment).


## CP-06 — идентификация AG-tools / lbjlaq/Antigravity-Manager (2026-10-10)
- Оригинал: https://github.com/lbjlaq/Antigravity-Manager (GitHub API доступен), создан 2025-11-26, последняя запись 2026-10-09. На момент проверки: 32030 stars, 3460 forks, 1730 open issues; это показатели популярности и нагрузки поддержки, НЕ аудит безопасности.
- Стек: Rust, Tauri v2, React; документация https://github.com/lbjlaq/Antigravity-Manager/blob/main/README.md, blob e6125b46e0e62f17bf631325c1007c4d922e8d8c.
- README подтверждает функции: OAuth account management, quota monitoring, smart rotation on 401/429, model mapping, OpenAI /v1/chat/completions, Anthropic /v1/messages, Gemini-compatible API, Docker/Windows/Linux/macOS; сервис по документации обычно на localhost:8045.
- Лицензия: проверенный LICENSE blob f1ba7b85b2b4ca4547d28599413dc48592d648f6 содержит Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0); коммерческую/производную интеграцию нужно отдельно юридически оценивать. GitHub API указывает license=other/NOASSERTION.
- Архитектурное отличие: AG-tools = независимый локальный proxy/gateway и account router; QNIX/AvenCores = патчеры локальных компонентов Antigravity IDE/CLI. Совместимость этих патчей с AG-tools НЕ установлена, для API-проксирования бинарный патч language_server.exe может быть не нужен.
- Безопасность: шлюз имеет доступ к OAuth credentials и может читать запросы/ответы клиентов; для тестов использовать isolated accounts, bind loopback, отдельный API key и WEB_PASSWORD, исключить токены из git/logs; не утверждать, что локальное пропатчивание снимает серверные ограничения.
- Статус: документационный и метаданный аудит проведён, runtime-тестов и детального review Rust исходников нет.

CURSOR: AG_pather / CP-06 COMPLETE (architecture/docs) → CP-07 Rust proxy token handling and network audit → CP-08 patcher-vs-AG-tools empirical compatibility.


## CP-07 — correction: AG-tools standalone integration and candidates (2026-10-10)
- Пользователь подтвердил практический дефект: lbjlaq/Antigravity-Manager не обеспечивает ожидаемую работу с AG Standalone и бесшовную смену аккаунта в его окружении. Прежняя схема CP-06 как готового рабочего шлюза для AG Standalone должна считаться архитектурной гипотезой, НЕ решением.
- Публичное подтверждение похожей ошибки: https://github.com/lbjlaq/Antigravity-Manager/issues/3221; различие keyring и SQLite путей, issue closed с упоминанием PR #3220; фактическая исправность на версии пользователя не тестировалась.
- Windows-кандидат: https://github.com/demusraph/antigravity-control-center — заявляет credential hot swap Windows Credential Manager, CDP-мониторинг/продолжение задач, квоты. Проверен README blob af83f37d5ea6f4bda4e30d8e8aae5a94d3279c01; фактическое обновление авторизации живого language_server.exe НЕ проверено.
- Linux standalone-кандидат: https://github.com/Muriel-Gasparini/antigravity-account-switcher — supervisor proxy с перехватом HTTP 429, автоматической ротацией и replay in-flight; README blob 32c792416a3bcdeec298a861b577abfa8dd1f8d9. Windows поддержка не подтверждена.
- Windows fallback: https://github.com/Doomd/antigravity-account-switcher — сохраняет профили и детектирует лимиты, но переключение с рестартом; НЕ соответствует требованию no-restart.
- Требования приемки: Windows + конкретный Standalone build; ручная/автоматическая смена без повторной авторизации; переключение активного language_server процесса; продолжение текущей задачи; безопасный escrow OAuth токенов; rollback; логирование без секретов. Не считать proxy/account rotation равным реальному seamless current-stream handoff.
- Заметка: механизм переключения не должен обходить серверные политики авторизации/допуска; проверять разрешения аккаунтов и условия поставщика.

CURSOR: AG_pather / CP-07 DISCOVERY COMPLETE → CP-08 source & behavior audit demusraph → CP-09 controlled Standalone validation.


## CP-08 — матрица всех шести кандидатов (2026-10-10)
Цель: Windows + Antigravity Standalone + ротация аккаунтов при квотах + отсутствие ручного re-login + непрерывность активной задачи.

| Кандидат | Механизм | Автопереключение | Без рестарта | Оценка применимости |
|---|---|---|---|---|
| demusraph/antigravity-control-center | Windows Credential Manager + лог LS + CDP resume | заявлено при HTTP 429 | заявлено | приоритет Windows PoC; не подтверждено, что LS перечитывает live token |
| Muriel-Gasparini/antigravity-account-switcher | scoped HTTP proxy/supervisor + replay запроса | заявлено | заявлено | сильный донор архитектуры, Linux-first, Windows не подтверждён |
| QNIX-Dev/eligibility-antigravity-patcher | патч локального eligibility + snapshot профилей CLI/IDE | ручное управление | не доказано | утилита патчинга/управления профилями, не бесшовный broker |
| AvenCores/open-antigravity-patcher | binary patch IDE/CLI | нет подтверждения | не доказано | только патч допуска; оригинал GitHub 404, архивы SourceForge |
| lbjlaq/Antigravity-Manager | отдельный OpenAI/Anthropic API gateway, account pool | заявлено для proxy | сценарий пользователя не работает | не считать заменой Standalone hot-swap |
| Doomd/antigravity-account-switcher | VSIX + PowerShell профили | предлагает переключиться | НЕТ (IDE restart) | не подходит для non-stop |

Свидетельства:
- https://github.com/demusraph/antigravity-control-center — README: hot swap WCM gemini:antigravity, daemon читает language_server.log, CDP resume
- https://github.com/Muriel-Gasparini/antigravity-account-switcher — README: Linux AG2.0, proxy, replay in-flight 429, fallback tier
- https://github.com/QNIX-Dev/eligibility-antigravity-patcher/blob/main/README.en.md — IDE SQLite отдельно от CLI/Manager credentials
- https://github.com/Doomd/antigravity-account-switcher — README явно требует restart
- https://github.com/lbjlaq/Antigravity-Manager/issues/3221 — IDE switching path defect
- https://sourceforge.net/projects/open-antigravity-patcher/files/V1.3.8/ — AvenCores архив

Никакого рейтинга безопасности по stars, без исполняемых тестов. Проверить прежде всего корректность обработки OAuth токенов, ключей и TLS/HTTP proxy (особенно replay и буфер 100MB), устойчивость CDP, совместимость с текущим Windows LS. Переключение локальных учётных данных не гарантирует обновление токена уже запущенным LS. Обход серверной авторизации не считается рабочим функционалом.

CURSOR: AG_pather / CP-08 COMPLETE (evidence matrix) → CP-09 Windows Control Center source security audit → CP-10 standalone runtime PoC.
