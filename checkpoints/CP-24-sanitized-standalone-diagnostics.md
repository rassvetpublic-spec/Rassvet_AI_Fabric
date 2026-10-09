# CP-24 — диагностика Antigravity Standalone без секретов

Дата: 2026-10-10
Ветка: AG_pather

## Новый интерфейс
- `src/raif_ag_supervisor/diagnostics.py` собирает только агрегированное состояние локального реестра и имена/PID найденных процессов.
- `src/raif_ag_supervisor/__main__.py` добавляет команду `python -m raif_ag_supervisor status`. На Windows каталог реестра берётся из LOCALAPPDATA/RAiF/AGSupervisor, допускается `--registry-dir`.
- Вывод содержит число зарегистрированных аккаунтов, наличие pending journal, ограниченный список процессов и явные `session_authorization_verified=false`, `hot_swap_verified=false`.
- Без чтения OAuth, почты, путей пользователей, аргументов командной строки процессов, сетевых запросов и модификации состояния приложения.
- `tests/test_diagnostics.py`: синтетические проверки отсутствующего реестра, редактирования отчёта, pending journal и CLI.

## Исполнение
- GitHub Actions для обычных коммитов в AG_pather по-прежнему выключен.
- Для проверки создано правило: одноразовая ветка `ag-ci-linux-cp24-20261010` даёт единственный Linux job. Windows CI отдельно после значимых Windows-изменений.
- Прямого исполнения на RASSVET_DESKTOP ещё нет: доступ к Desktop Commander был ограничен месячной квотой.

## Ограничения
- Диагностика не может подтвердить реального активного пользователя Standalone и не умеет переключать токены.
- Статусы `verified=false` — намеренный безопасный ответ до реального runtime-теста.
- Работа с реальными токенами не проводилась.

## Статус
CP-24 CODE_COMMITTED; CI_PENDING (до появления контрольного запуска).

## Курсор
AG_pather → CP-24 VERIFY_LINUX_CI → CP-25 RASSVET_DESKTOP_STANDALONE_SESSION_DIAGNOSTICS.
