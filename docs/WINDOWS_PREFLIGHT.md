# Предварительная проверка Windows без обращения к моделям

**Версия:** 1.0. **Статус:** готово для проверки на Windows-исполнителе GitHub Actions; личный компьютер владельца не проверен. **Язык:** русский.

## Назначение

Режим read-only обнаруживает наличие Python, Git, Codex, Antigravity и NVIDIA, а также необходимых файлов проекта. Он **не** читает `.codex`, `auth.json`, cookie, локальную историю, файлы BPR40, любые токены авторизации; не выполняет обращений к моделям и не создаёт базу данных.

В Windows PowerShell (из корня проекта):

1. `./scripts/windows-preflight.ps1 -RequireWindows` — сформировать JSON-отчёт о доступности компонентов, не запуская Codex/Antigravity.
2. `./scripts/run-tests.ps1` — тесты Python (без облачных моделей).
3. `./scripts/demo.ps1` — создать временную базу `%TEMP%` и проверить `mock`-задачу. Это действие **записывает только новую тестовую БД** в TEMP; не смешивать с read-only проверкой.

Результат предварительной проверки имеет `schema=RAI_FABRIC_WINDOWS_PREFLIGHT/1` и `verdict=PASS/PARTIAL`. `PASS` подтверждает **только доступность Python 3.11+ и структуры проекта**. Обнаружение команд `codex`, `agy`, `nvidia-smi` не доказывает работоспособность их моделей, наличие авторизации, квоты или VRAM.

## Windows CI

Файл `.github/workflows/windows-readonly.yml` запускает два отдельных набора проверок на `windows-latest`: Python 3.11 и 3.13. Нет AI-вызовов, нет доступа к приватным компьютерам или подпискам. Права `GITHUB_TOKEN` ограничены `contents: read`; checkout не сохраняет токен.

Успешный CI подтверждает поведение GitHub-hosted Windows runner, **но не** конфигурацию личного компьютера владельца, его Codex или Antigravity.

## Диагностика Codex и подписки

Проверка обнаруживает **только команду** `codex`. Она не читает авторизацию и не выполняет `codex app-server` или модельный запрос. Для проверки подписного канала нужен отдельный явный запуск OAuth + App Server с проверкой `chatgpt.tokens.use.direct` и терминального события `turn/completed`. Доступность тарифа, подписки, модели и лимитов без этого не подтверждается.

Источники: [Codex App Server](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server), [ограничения подписного режима](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations).

## Безопасность

Запрещены обход внутренних endpoint веб-чата, извлечение cookie, просмотр профилей Codex и запись в BPR40. Статусы `NOT_TESTED` нельзя выдавать за `PASS`. После каждого этапа фиксируйте чекпойнт, реальное evidence и новый курсор.
