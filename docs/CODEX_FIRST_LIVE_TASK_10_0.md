# RAiF 10.0 — первая разрешённая модельная задача через SQLite

**Статус на 10.10.2026:** `HOST_PASS_WITH_SCOPE`. Первый реальный Codex turn на Windows завершён; 3/3 теста PASS. См. чекпойнт `RAI_FABRIC_10_0B_FIRST_LIVE_TURN_WINDOWS_VERIFIED_2026-10-10_R1.json`. Вся остальная автономия — не проверена.

## Цель и безопасные границы

Один подписной `turn/start` Codex App Server получает минимальную задачу на создание `arithmetic.py`, возвращает исходник как JSON. Собственный Fabric проверяет структуру AST, пишет файл только в **новый пустой** каталог `_RAIF_RUNTIME/CODEX_LIVE_<ID>/workspace`, формирует локальные тесты и исполняет `unittest`. В SQLite сохраняются lease, SHA-256, результат и следующий курсор. Ни один файл пяти продуктовых подсистем не изменяется.

- Пользователь прямо разрешил **один реальный модельный turn**. Это не обещание одного внутреннего HTTP-запроса: Codex может выполнять собственные внутренние операции в рамках одного turn. Повторный `turn/start` и скрытый API fallback запрещены.
- Для авторизации применяется штатная команда `codex login` в **отдельном** `CODEX_HOME` под `%LOCALAPPDATA%/Rassvet_AI_Fabric/`; пользователь входит в ChatGPT через браузер. Существующие учётные файлы Codex не копируются, не читаются и не перезаписываются. Логирование паролей, кодов и токенов не выполняется.
- Перед вызовом проверяется `codex login status`: допускается только `Logged in using ChatGPT`. Любая API-key-only авторизация даёт BLOCKED.
- `OPENAI_API_KEY`, `CODEX_API_KEY`, `CODEX_ACCESS_TOKEN` и другие переменные оплаты удаляются из среды процесса; поэтому программа не может незаметно воспользоваться API-key fallback. В App Server используется штатный Codex ChatGPT login, без пользовательского веб-скрейпинга.
- RPC: `initialize` → `initialized` → `thread/start` (`sandbox: read-only`, `approvalPolicy: on-request`) → **один** `turn/start` → `turn/completed` со статусом `completed`.
- Запросы на одобрение инструментов, событие запуска shell/fileChange и неожиданные RPC IDs немедленно блокируют результат. Автоматического разрешения нет.
- Защита от повторного запуска: стабильный локальный marker `ONE_TURN_10_0_CONSUMED.json` создаётся эксклюзивно в `_RAIF_RUNTIME` перед модельным запуском. Даже при сетевой ошибке автоматический повтор не выполняется, пока оператор не проведёт отдельную сверку.
- При обрыве канала, отмене или истечении срока — BLOCKED, без автоповтора. Тайм-аут 120 секунд. API-биллинг = «не измерялся», не выдумывать ноль стоимости; квота подписки может расходоваться.
- Результат `RAiF-Windows-RESULT-CODEX-LIVE-*.zip` сохраняется непосредственно в `C:\GIT\Rassvet_AI_Fabric` и содержит **только** очищенные отчёты, файл с ограниченным AST и локальные тесты. Токены, коды входа, полные RPC-ответы, реальные пути профиля исключаются.

## Функциональная приёмка

1. Реальный установленный `codex.exe` прошёл SHA-256 пиннинг, версия команд и ChatGPT login подтверждены локально.
2. В SQLite ровно одна `codex-app` задача с одним захватом lease.
3. Модельный `turn` завершился `completed`, без запроса shell/permission.
4. Строго допустимый исходник сохранён в изолированном workspace, 3 локальных теста PASS.
5. Архив результатов сформирован в корне проекта; чекпойнт содержит source/test SHA, статус и события без секретов.

Это **MVP-проверка** разработчика, не промышленная автономия: Git worktrees, сложные задачи, независимый review и Job Objects ещё не реализованы.

## Правила CI и источники

Новые Linux/macOS jobs не создавать; один контрольный Windows CI при изменении кода. Не включать донорские решения в README. Обязательные источники: [Codex App Server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server) и [Preview limitations](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Фактический host-result от 10.10.2026

- Локальный ZIP `RAiF-Windows-RESULT-CODEX-LIVE-20261010_063500_b123dc17.zip`: SHA-256 `7b7ec56d67f44ed9cd7bfef571153937c83050b91380d811974af211aebeda3d`, ZIP CRC PASS. Повторно присланная копия побайтно совпадает.
- Протокол: `initialize`, `initialized`, `thread/start`, один `turn/start`; по очищенному отчёту `model_turn_started=true`, `model_turn_completed=true`, `simulation=false`, `tool_actions_seen=false`, `child_cleanup=GRACEFUL_OR_EXITED`.
- SQLite-задача `COMPLETE`, checkpoint `PASS`, указатель `REVIEW_GENERATED_CODE`. `source_sha256=ba1a531f581d2e6094e978ed6f7aca7a8d92eeb62c6e7ad73ee692f7f18bc772`, `test_sha256=5ec06b837fd70e0e252a89c7fb92dba96e288e4301d5347116ba35405e74bf5f`; оба хеша независимо пересчитаны по файлам из ZIP.
- `STAGES.jsonl`: 20 событий, 10 этапов PASS, ошибок нет. CLI сообщает `CHATGPT_PLAN_CLI_SIGNED_IN`, выключенный API-key fallback и одноразовое резервирование согласия. Эти показатели **подтверждены локальным отчётом**, а не независимой оценкой поставщика.
- Один модельный turn не равен одному внутреннему HTTP-запросу; реальный остаток квоты и денежный биллинг не измерялись. Нельзя изолированную задачу `arithmetic.py` считать автономной разработкой пяти подсистем.
- Один успешный вызов исчерпал разрешение на испытание этапа 10.0: **не запускать повторно старый PS1 и не удалять one-turn marker**. Следующий модельный запрос — отдельное явное разрешение.

## Следующий продуктовый этап 10.1

Реализовать **без обращения к модели**: изолированный Git worktree из pin SHA, файловую allowlist, безопасный diff, независимые тесты и отказ от автоматического merge; сохранить checkpoint и audit, протестировать fail-closed на Windows. Только затем согласовать новую модельную задачу в демо-репозитории. Не изменять CKS Canon, RULESHUB, CONTROL TOWER и BPR40 без отдельного gate.

**Следующий курсор:** `RAI-FABRIC/10.1-SAFE_WORKTREE_DIFF_REVIEW_OFFLINE`.
