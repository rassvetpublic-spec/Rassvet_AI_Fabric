# CP-52B — подготовка защищённого механизма возврата исходной сессии Standalone

Дата: 2026-10-10. Ветка: AG_pather. Статус: PACKAGE_PREPARED_STATIC_QA_PASS / WINDOWS_RUNTIME_PENDING.

## Факты CP-52A
- Получен RAiF_AG_CP52A_RESULT_20261010_054943_b4e96ea1.zip; SHA-256 b2b9c5c2ea794876b33d2b1d916a478ea644354b4e1d83130690b3b3bbd8701a.
- ZIP CRC OK, 5 разрешённых файлов. `SUCCESS`, `DRYRUN_READY_FIVE_CANDIDATES`. Журнал: 53 события, 1 необязательное предупреждение LOCAL_INTERFACE_UNAVAILABLE, ошибок нет.
- RAiF registry 9 и vault targets 9; 5/5 кандидатов имеют сохранённые записи; транзакция recovery не ожидается.
- Standalone 2.22.0, Antigravity 6 процессов, Language Server 1 процесс (PID 14976), start UTC 2026-10-10T00:41:40.1206590Z; fingerprint пропатченного LS совпал, короткий снимок PID стабилен.
- AG-tools не запущен, localhost:19527 недоступен, сведения о реальных квотах отсутствуют.
- `LIVE_SWITCH_GATED_NO_VERIFIED_RESTORE`: 0 переключений/пингов, no approved switch adapter, no native rollback snapshot.

## Архитектура CP-52B
Задача — устранить предшествующий **restore safety gate**, не меняя native `gemini:antigravity`:
1. PowerShell 7 Windows-only. Win32 CredRead только локально и в памяти пользователя; нельзя выводить содержимое credential blob, email или токены в stdout/ZIP.
2. В режиме `PrepareRollback` **при явном флаге `-ConfirmSecureBackup`** сохраняет полный текущий нативный credential record (binary blob + minimal restore metadata) в DPAPI CurrentUser-защищённом файле, проверяет восстановление из шифротекста в памяти, побайтовое совпадение с оригиналом. Папка резервной записи с ACL текущего SID и LocalSystem.
3. Локальный путь encrypted-only: `%LOCALAPPDATA%\RaIF\AGSupervisor\rollback\cp52b-native-credential.dpapi` (реальный каталог `RAiF`, регистр пути в Windows некритичен). Файл **не** экспортируется ни в ZIP, ни в GitHub, ни в CI. Не переносить его на другую машину.
4. Если encrypted-only файл уже есть, не перезаписывать; проверить DPAPI roundtrip и совпадение с текущей сессией, иначе безопасно остановиться.
5. `Inspect` — только read-only; `VerifyRollback` — read-only проверка существующего DPAPI снимка.
6. `RestoreNative` существует как **аварийная** команда, но требует двух флагов `-ConfirmNativeRestore -ConfirmSessionStopped` и фактического отсутствия процессов Antigravity и Language Server; запись только native `gemini:antigravity`, без перезапуска приложения. Не включать этот режим без необходимости и явного решения пользователя.
7. Запись native credentials не выполняется в `PrepareRollback`. Программно отсутствуют сетевые обращения, OAuth refresh, патчинг бинарника и остановка/запуск процессов. Успешная DPAPI readback проверка не доказывает, что восстановленная авторизация будет принята провайдером или что активный LS автоматически перечитает запись.
8. Структура credential классифицируется по **локально прочитанным полям только в памяти**: native v2 token / other JSON / opaque; значения секретов не покидают Windows пользователя.
9. Итоговый ZIP в корне проекта содержит только `STATUS.txt`, `SUMMARY.txt`, `RECEIPT.json`, `STEPS.jsonl`, `report.json`; в отчёте только стадии, коды и общие флаги. Снимать полный стек/exception message запрещено.

## Передача пользователю
- `RAiF_AG_CP52B_SecureRollback.zip` SHA-256 `9A9FB82F6E9A27ABEEE6698B353CEFE77D13AA142E5C744D3D5FFA4F21193106`.
- `RAiF_AG_CP52B_Run.ps1` SHA-256 `83ED91E6E262169084929BA8CC5924F4F9BBBBAA00AC765144B07BA33A9776FB`.
- Оба файла скачиваются в `D:\ЗАГРУЗКИ` рядом. ZIP вручную не распаковывать.
- Одна явная команда подготовки безопасного возврата:
  `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP52B_Run.ps1" -Mode PrepareRollback -ConfirmSecureBackup`
- Архив результата: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP52B_RESULT_<runid>.zip`.
- Пакет и исполняемые исходники существуют только как вложения в чат; публичный GitHub содержит только проектный чекпойнт.

## Статические тесты и границы
- ZIP CRC PASS, закреплённый SHA-256 найден в ASCII launcher, 2 строго ожидаемых файла в ZIP.
- В коде проверены DPAPI CurrentUser, user-only directory ACL, двойной gate для аварийного restore, отсутствие сетевых/процессных команд и явный запрет неожиданной native записи.
- PowerShell 7 теста на RASSVET_DESKTOP **ещё нет**. Динамическая работоспособность и способность реально восстановить сессию не заявляются.
- Следующий реальный switch только после отдельной проверки результата и при явном подтверждении; ограничение 60 секунд и 5 аккаунтов действует на весь будущий live test, а не на эту подготовку.

## CURSOR
AG_pather / CP-52A VERIFIED → CP-52B PREPARE_ENCRYPTED_NATIVE_ROLLBACK → CP-53 CONFIRMED_SAFE_60S_5_ACCOUNT_LIVE_TEST.
