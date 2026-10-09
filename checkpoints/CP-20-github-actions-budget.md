# CP-20 — бюджет GitHub Actions и правила запуска CI

Дата: 2026-10-10
Ветка: AG_pather

## Диагностика
- Через GitHub API найдено **20 запусков** `AG Supervisor Tests` в ветке `AG_pather` до изменения политики.
- Исходная конфигурация запускала Linux + Windows на каждый push, включая коммиты чекпойнтов.
- Проверить фактические оплаченные минуты и остаток лимита через доступный GitHub-коннектор не удалось: доступ к API биллинга отсутствует. Не выводить расход минут из числа запусков как точные данные.

## Применённая политика
- Обычные коммиты в `AG_pather` теперь **не запускают** GitHub Actions.
- Для контрольного Linux теста: создать tag `ag-ci-linux-<checkpoint>` на нужном коммите.
- Для Linux + Windows: создать tag `ag-ci-full-<checkpoint>` на нужном коммите.
- `workflow_dispatch` допускает ручное выполнение (Windows opt-in), но для интерфейса GitHub workflow должен присутствовать в default branch; пока он только в `AG_pather`, следует использовать validation tags.
- `unit-windows` запускается только для `ag-ci-full-*` или явного выбора Windows при доступном ручном запуске.
- Установлены ограничения длительности: Linux 5 минут, Windows 7 минут; concurrency cancel-in-progress и минимальные GitHub permissions (`contents: read`).
- Писать тесты и делать коммиты локально/пакетами, GitHub Actions запускать по одной контрольной точке после значимых изменений, не на каждый исходный файл.
- Счётчик run и политика могут периодически проверяться через GitHub API без запуска Actions. При доступности billing отдельно сверять квоты/бюджет.

## Контрольные критерии
1. Последующие обычные push в ветку не создают workflow run.
2. `ag-ci-linux-*` запускает только Linux.
3. `ag-ci-full-*` запускает Linux и Windows.
4. Нет секретов в GitHub Actions, логах и артефактах.
5. Повторно анализировать расход перед следующей платной или ресурсоёмкой проверкой.

## Статус и курсор
CP-20 POLICY_APPLIED / BILLING_UNAVAILABLE
Следующий курсор: AG_pather → CP-21 VERIFY_NO_PUSH_CI → CP-22 TAG_CONTROLLED_VALIDATION → CP-23 SAFE_REGISTRY_IMPLEMENTATION.
