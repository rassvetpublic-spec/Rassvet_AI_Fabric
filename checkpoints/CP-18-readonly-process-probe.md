# CP-18 — безопасная диагностика Standalone (без изменения сессии)

Дата: 2026-10-10

## Реализация
- `src/raif_ag_supervisor/session_probe.py`: только чтение вывода `tasklist.exe /fo csv /nh`.
- Узкий allowlist имён процессов: Antigravity.exe, language_server.exe, agy.exe, Antigravity IDE.exe.
- Возвращаются только имя исполняемого файла и PID, без командной строки, путей, окружения, токенов и пользовательских данных.
- `tests/test_session_probe.py`: парсинг CSV, неверный PID, дубликаты, проверка отсутствия полей с секретами и Windows read-only smoke test.

## Важное ограничение
Наличие процесса не означает подтверждённую активную авторизацию, доступную квоту или возможность живого переключения токенов. GitHub Windows runner не содержит пользовательской установки Standalone, поэтому функциональная совместимость с ней остаётся НЕПРОВЕРЕННОЙ.

## Статус
Код и синтетические тесты сохранены. Прогон Linux + Windows для коммита bdb774e40dc3496f5269e641b5acde7d42efd7f2 завершился успешно: https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38001287850 . Никаких живых OAuth-данных, бинарных патчей или перезапусков приложения не было.

## Курсор
AG_pather → CP-18 VERIFY_CI → CP-19 PERSISTENT_REGISTRY_AND_CRASH_RECOVERY → CP-20 REAL_STANDALONE_AUTH_STATE_TEST.
