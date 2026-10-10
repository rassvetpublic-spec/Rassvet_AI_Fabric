# CP-25 — полный контроль запусков GitHub Actions

Дата: 2026-10-10
Репозиторий: rassvetpublic-spec/Rassvet_AI_Fabric

## Инвентаризация через GitHub API (только чтение)
- Всего зарегистрировано 32 workflow runs.
- `AG Supervisor Tests`: 22 запуска, из них 20 исторических в AG_pather и ровно два выборочных запуска на валидационных ветках `ag-ci-full-cp23-20261010` и `ag-ci-linux-cp24-20261010`.
- `Проверка Windows без облачных моделей`: 10 запусков в main, 9 success и 1 failure.
- Для workflow main: 20 Windows matrix jobs (Python 3.11 и 3.13), суммарное измеренное GitHub API время заданий 533 секунд (~8 мин 53 сек).
- 533 секунды — сумма длительностей jobs, НЕ точные тарифицируемые минуты. Бюджет GitHub Actions и возможное округление/OS-множители через доступный коннектор не подтверждены.

## Обнаруженный расходный триггер
- Файл main: `.github/workflows/windows-readonly.yml`; триггеры push для main, pull_request, workflow_dispatch.
- Каждый push в main запускает две Windows jobs (Python 3.11 и Python 3.13), limit timeout 15 минут на каждую.
- В отличие от `AG_pather`, автоматические проверки main пока НЕ ограничены контрольными ветками/тегами. Изменения main без отдельного согласованного плана НЕ делались.

## Политика
1. AG_pather — ordinary commits без CI; разовые проверки на ветках `ag-ci-linux-*` и `ag-ci-full-*`.
2. CI-ветки CP-23 и CP-24 дали один Linux+Windows success и один Linux-only success; дополнительных прогонов не создавать без существенного изменения кода.
3. Перед push в main учитывать матрицу двух Windows jobs; оптимизация main CI должна быть отдельным изменением и сопровождаться сохранением обязательных проверок.
4. Мониторить GitHub API read-only; нет доступа к точным GitHub billing usage/remaining. Никогда не вычислять биллинговый остаток из запусков.

## Статус
CP-25 USAGE_INVENTORY_COMPLETE / MAIN_CI_COST_RISK_IDENTIFIED / BILLING_UNAVAILABLE.

## Курсор
AG_pather → CP-26 / REAL_STANDALONE_LOCAL_DIAGNOSTICS_BLOCKED_BY_DC_LIMIT → CP-27 / SESSION_SWITCH_VALIDATION_DESIGN.
