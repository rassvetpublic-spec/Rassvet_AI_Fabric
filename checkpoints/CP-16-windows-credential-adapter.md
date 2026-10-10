# CP-16 — Windows Credential Manager Adapter

Дата: 2026-10-10
Ветка: AG_pather

## Реализовано
1. Добавлен `src/raif_ag_supervisor/windows_vault.py`: изолированные Generic Credentials только в `RAiF_AG_Supervisor:account:` для текущего пользователя Windows.
2. Реализованы `put`, `has`, `delete`, проверка идентификаторов, ограничение 2560 байт, idempotent delete, очистка временного native-буфера и сообщения об ошибках без значений учётных данных.
3. НЕТ чтения токенов наружу, изменения записей `gemini:antigravity`, модификации `language_server.exe`, сетевых запросов или переключения Standalone.
4. `AccountRecord.credential` скрыт из стандартного `repr`.
5. Добавлены тесты синтетического Windows Credential Manager и тест на отсутствие секрета в `repr`.
6. CI расширен до Linux + Windows; для Windows установлены PYTHONUTF8 и PYTHONIOENCODING=utf-8.

## Результаты проверки
- На первом запуске Windows CI с новым заданием нативный round-trip `CredWriteW/CredReadW/CredDeleteW` прошёл.
- Windows full suite обнаружил существующий сбой теста CLI с кодировкой `charmap`; причина в настройке консольного кодирования subprocess. Добавлена коррекция UTF-8 в job environment; окончательный результат повторного запуска нужно подтвердить по GitHub Actions.
- Запуск Windows тестов выполняется только с синтетическими данными и временными ключами, удаляемыми при завершении теста.
- Пределы безопасности: промежуточные Python `str` и `bytes` нельзя надёжно очистить из памяти; на данном этапе адаптер не считается production-ready.

## Инварианты
- Никаких пользовательских OAuth токенов в GitHub, CI, логах или документах.
- Windows-хранилище RAiF не вмешивается в нативные записи Antigravity.
- Реальное автоматическое переключение аккаунта пока НЕ подтверждено.

## Курсор
AG_pather / CP-16 IMPLEMENTED + WINDOWS_SMOKE_PASS → CP-16_VERIFY_WINDOWS_FULL_CI → CP-17 LOCAL_IMPORT_TRANSACTION → CP-18 STANDALONE_SESSION_PROBE.
