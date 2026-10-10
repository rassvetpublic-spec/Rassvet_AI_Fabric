# CP-48–51 — пакетный аудит Windows Standalone и RAiF Vault

Дата: 2026-10-10. Ветка: `AG_pather`. Статус: `SUCCESS_WITH_LIMITATIONS`.

## Проверенный локальный RESULT ZIP

- Получен `RAiF_AG_CP48_51_RESULT_20261010_053229_22381d89.zip`.
- SHA-256 архива: `78de2b53ac364faa5075dd3b4e803b81caa662a6724539bf91a204d8bffdbbe2`.
- ZIP CRC успешен. Файлы: `STATUS.txt`, `SUMMARY.txt`, `RECEIPT.json`, `STEPS.jsonl`, `report.json`. Исходный аккаунтный JSON и содержимое секретов в архив не вошли.
- `RECEIPT.json`: `RAIF_AG_CP48_51_BATCH_READONLY`, `status=SUCCESS`, `exit_code=0`, `probe_exit_code=0`, подтверждена сверка SHA-256 входного пакета.
- `STEPS.jsonl`: 42 события (20 start, 22 ok), ошибок/предупреждений нет.

## CP-48 — хранилище

- Из исходного отчёта: `registry_present=true`, `registry_valid=true`, `registered_accounts=9`, `credentials_present=9`, `recovery_pending=false`, `verdict=PASS_9_OF_9_TARGETS_FOUND`.
- Это подтверждает существование записей и сохранность метаданных, но не возможность получить новые действительные OAuth access-токены.

## CP-49 — основание доверия к профилям

- `kind=user_attestation`, `reported_working_accounts=9`, `provider_oauth_retested=false`, `standalone_identity_verified=false`, `verdict=USER_REPORTED_AGTOOLS_ONLY`.
- Пользователь ранее подтвердил практическую работу всех 9 аккаунтов через AG-tools. Пакет не выполнял повторную OAuth-проверку и не доказывает доступность каждого профиля в Standalone.

## CP-50 — квоты

- Локальный интерфейс `127.0.0.1:19527`: `api_available=false`, `verdict=INTERFACE_UNAVAILABLE`.
- AG-tools не был запущен (0 найденных процессов). Из отсутствия HTTP API нельзя заключать, что квот нет или что аккаунты не работают.
- Сетевые запросы к Google отсутствовали. Никакие проценты квот не выдумывать. Дальнейший сбор — через явно поддерживаемый read-only интерфейс после проверки его включения, либо через отдельный санкционированный адаптер.

## CP-51 — процессы и патч

- Найден один запущенный `language_server.exe` и шесть процессов Antigravity.
- SHA-256 установленного Language Server совпадает с CP-31 после патча; наличие native credential target подтверждено без чтения.
- `active_account_verified=false`, `hot_swap_verified=false`, `verdict=PROCESS_OBSERVED_ONLY`.
- Никакие учётные данные, процессы или бинарники не менялись.

## Инварианты и ограничения

- Повторный импорт и повторный патч не нужны.
- Нельзя считать автоматически доказанным, что смена Windows Credential Manager приводит к смене уже закэшированной авторизации Language Server.
- До отдельного согласованного PoC переключения не менять native `gemini:antigravity`, не перезапускать приложение, не устанавливать другие бинарные патчи.
- Секреты, email, исходный JSON, содержимое Credential Manager, процессы и пользовательские файлы не публиковать в GitHub.
- Для теста CP-52 обязательно определить способ безопасного восстановления исходной сессии, ограничить эксперимент двумя аккаунтами и зафиксировать факт возможного рестарта; без доказательств не обещать hot swap.

## Текущий курсор

`AG_pather / CP-48 PASS + CP-49 USER_ATTESTED + CP-50 API_UNAVAILABLE + CP-51 PROCESS_OBSERVED → CP-52 CONTROLLED_SWITCH_DESIGN → CP-53 SINGLE_SWITCH_AND_RESTORE_TEST`.
