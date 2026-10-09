# CP-32 — QNIX-Dev real hot-swap audit / RAiF trial decision

Дата: 2026-10-10. Windows-only, Antigravity Standalone.

## Проверенный источник
- https://github.com/QNIX-Dev/eligibility-antigravity-patcher
- `manager.py` blob SHA `544b1aa3e438804b02aa32bb395544cc6f2493ef`.
- `README.en.md` blob SHA `cd4fb67ac688ca53d709212f688c63a0178a776c`.

## Реальное поведение QNIX
1. `acct_use()` проверяет `_accounts_busy(target_type)`; при занятом приложении выводит «close ... first - the token is cached in memory while running» и завершает операцию.
2. При переключении `_apply()` меняет сохранённые учётные данные Windows Credential Manager для scope cli-manager или SQLite state.vscdb для scope IDE, после чего сообщает «(re)start Antigravity to use it».
3. Это offline profile switch без нового браузерного логина, **не** подтверждённый live hot swap, **не** автоматический handoff текущего stream.
4. `acct_save()` снимает snapshot из *уже существующей активной* сессии; без рабочего входа через браузер профиль непосредственно из пары `email, refresh_token` командой save создать нельзя.
5. `acct_usage()` умеет читать квоты сохранённых или текущей активной сессии, может обновить access-токен в памяти; эту функцию нельзя приравнивать к переключению учётки в живом Standalone.
6. `gate_patch()` вызывает `make_backup()` и создаёт `.agybak`; пользователь предпочёл НЕ создавать бэкапы, поэтому штатный QNIX patch расходится с предпочтением.

## Выбор для первого испытания
- Предпочтительный: готовый RAiF CP-31 (локальное изменение ровно одного auth-gate после проверки уникальной сигнатуры, без резервной копии). Задача: попытаться устранить зависание на welcome/sign in. На целевом бинарнике ещё НЕ испытан.
- Не применять QNIX и RAiF CP-31 последовательно к одному файлу: пересечение области изменения, конфликт состояния, риск нераспознанного уже изменённого бинарника.
- Если CP-31 возвращает unsupported signature, НЕ подбирать байты автоматически. Получить только обезличенный отчёт и уточнить версию бинарника.
- После работающего входа — отдельно внедрить управление account pool и наблюдение состояния Language Server. «No restart» принимать только после независимого runtime evidence из CP-26.
- Старые пользовательские refresh tokens не публиковать, не использовать для тестов CI, не вкладывать в отчёты или GitHub.
- Локальное исправление проверки не гарантирует серверную авторизацию/геодоступ; нарушение политик допуска не считать устранённым серверным доступом.

## Проверка / статус
QNIX source-backed audit COMPLETE; RAiF CP-31 PACKAGE_READY but NOT_RUN_ON_TARGET; live hot swap NOT_IMPLEMENTED.
No GitHub Actions requested or started for this checkpoint.

## CURSOR
AG_pather → CP-32 QNIX_SWITCH_BEHAVIOR_VERIFIED → CP-33 RUN_RAIF_CP31_AND_RECEIVE_RESULT → CP-34 LOGIN_RETEST → CP-35 STANDALONE_SESSION_SWITCH_POC.
