# CP-27 — Windows-only CI и учёт бесплатных стандартных runners

Дата: 2026-10-10. Источник истины: актуальная публичная документация GitHub и GitHub API.

## Проверенный факт
- Репозиторий `rassvetpublic-spec/Rassvet_AI_Fabric` имеет visibility=public (GitHub API, 2026-10-10).
- Для **публичных** репозиториев стандартные GitHub-hosted runners, включая `windows-latest`, предоставляются бесплатно без помесячного списания лимита вычислительных минут.
- **Larger runners** не подпадают под эту бесплатность; после изменения visibility на private стандартные runners используют квоту/биллинг владельца.
- Бесплатность не снимает ограничений по параллельности, ресурсам, артефактам, хранению, времени выполнения и допустимому использованию. Например, GitHub Free: 20 одновременных стандартных jobs; лимиты могут меняться в зависимости от плана.
- Срок хранения GitHub Actions logs/artifacts по умолчанию 90 дней, для публичных репозиториев настраивается в пределах 1–90 дней. Наш workflow не загружает артефакты.
- Бюджет GitHub Actions, кеши и retention конкретного аккаунта не подтверждены через доступные настройки биллинга; указанные параметры не являются измерением пользовательских затрат.

## Применённая конфигурация AG_pather
- Только `windows-latest`; Linux job удалён из активного `ag-supervisor-tests.yml`.
- Автоматический `push` по ветке `AG_pather` только если изменены `src/**`, `tests/**`, `pyproject.toml`, `scripts/run-tests.ps1` или сам workflow.
- Изменения `checkpoints/**` и прочей документации не запускают CI.
- Совместимость специальных `ag-ci-win-*` веток/тегов и `workflow_dispatch` сохранена.
- Предохранитель: job выполняется только когда `github.event.repository.private == false`; при приватизации job будет пропущен.
- Одна Windows job на Python 3.12, `timeout-minutes: 7`, `concurrency.cancel-in-progress: true`, `contents: read`, `persist-credentials: false`.
- Не публиковать токены, личные данные, дампы Credential Manager, содержимое секретных JSON в CI или артефактах.
- Режим `main` не изменён; там отдельно существует Windows-only workflow с матрицей Python 3.11/3.13.

## Исправление прежней трактовки
- Старые CP-20/CP-25 корректно описывают исторические запуски, но их предположение, будто каждый запуск публичного Windows job расходует платные минуты, **не применяется** в текущей public-конфигурации.
- Отслеживать теперь в первую очередь: изменение visibility, использование larger runners, job concurrency, неожиданные частые/длинные запуски, выполнение запрещённых сценариев, артефакты/retention, failures.

## Ссылки GitHub
- https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/reference/limits
- https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository

## CHECKPOINT/CURSOR
CP-27 WINDOWS_ONLY_PUBLIC_POLICY_APPLIED; Windows CI run is to be verified separately.
Курсор: AG_pather → CP-27_VERIFY_WINDOWS_JOB → CP-28_LOCAL_AUTH_OBSERVER_DESIGN → CP-29_RASSVET_DESKTOP_RUNTIME_VALIDATION.
