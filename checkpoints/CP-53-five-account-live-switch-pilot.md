# CP-53 — пять аккаунтов / 60 секунд, рабочий эксперимент Standalone

Дата: 2026-10-10. Ветка AG_pather.
Статус: PACKAGE_STATIC_CHECK_PASS; пользовательский PowerShell 7 запуск не производился.

## Фактическое основание
- CP-52D результат: SUCCESS, 54 события без ошибок, DPAPI CurrentUser v2 snapshot создан и прочитан с точным совпадением исходного native credential blob; синтетический WinCred canary write/read/delete PASS.
- ZIP SHA-256 CP-52D result: 6ac9d00ad1935ea8fcaba17f49bcf726b137640a35b9334727cd9d95e82a327b.
- CP-52A: 9/9 RAiF Vault, пять кандидатов по наличию записей. Все 9 аккаунтов в AG-tools функциональны по прямому сообщению пользователя (без повторного OAuth).
- Патч language_server из CP-31 стабилен.
- Не повторять никакие backup/preview/import без необходимости.

## Подготовленный CP-53 (опт-ин live)
- Комплект ZIP + PS1 для Windows PowerShell 7; отбор пяти свежих локально кэшированных аккаунтов из каталога AG-tools по совпадению refresh tokens с 9 RAiF Vault entries **строго в памяти пользователя**.
- Никакие 9 секретов/почты не включены в комплект и не выводятся в результат. Код не копирует лицензионные исходники AG-tools; использует наблюдаемый протокол формата пользовательских данных и документированный Win32 API.
- Предварительно читает и проверяет CP-52D DPAPI CurrentUser v2 snapshot на побайтовое совпадение с текущим native credential. При mismatch или менее пяти свежих cached access tokens — fail-closed, без записи.
- Режим Preview: только проверка. Режим Live требует **двух явных флагов**: `-ConfirmLiveSwitch -ConfirmChildRespawn`.
- В режиме Live: для каждого из пяти кандидатов записывает корректный v2 JSON токен в `gemini:antigravity`, читает обратно и сравнивает, завершает **только дочерний language_server** (не основное окно приложения), ожидает появления нового дочернего процесса. Делает краткий Google userinfo GET для проверки идентичности токена (не того, какой токен использует Standalone). Лимит исполнения цикла: резерв для возврата, общий целевой бюджет 60 секунд.
- После последнего шага или ошибки **в finally восстанавливает исходную нативную запись** из проверенного DPAPI и пытается повторно запустить дочерний LS через supervisor. Результат фиксирует отдельные флаги original_native_restored и original_child_respawned. При отсутствии возобновления дочернего процесса не заявлять SUCCESS.
- Защита от неожиданного прерывания: локальный nonsecret `cp53-active-test.marker`; режим `Recover` с `-ConfirmRecovery` для ручного восстановления после сбоя. Восстановление активной генерации после child respawn не подтверждено.
- Если child процесс не возрождается, отчёт CHILD_DID_NOT_RESPAWN; native backup восстанавливается, для перезапуска работающего приложения может потребоваться ручное действие.
- Полные стадийные STEPS.jsonl, receipt, report без tokens, emails или cached source JSON. Результат в корень `C:\GIT\Rassvet_AI_Fabric`.

## Артефакты и команда
- `RAiF_AG_CP53_FiveAccount.zip` SHA-256 `FFA1D3E28705B95679EC0148E09B6CA55326F258F65F0444F16B212DC871D83E`.
- `RAiF_AG_CP53_Run.ps1` SHA-256 `70851AB1BE11C69C1C8E438F30A1EDCA89309ADFD9A1EBD8BDED16519FB9A3D0`.
- Оба файла рядом в `D:\ЗАГРУЗКИ`. `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP53_Run.ps1" -Mode Live -ConfirmLiveSwitch -ConfirmChildRespawn`.
- Итог `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP53_RESULT_<runid>.zip`.
- Режим Recover, если потребуется: тот же PS1 `-Mode Recover -ConfirmRecovery`.

## Честные ограничения и качество
- ZIP CRC, SHA pin, ASCII launcher, отсутствие CredDelete native, проверка стадийного журнала, AST parser в launcher **перед побочными эффектами** — пройдены статически.
- Нет Windows runtime в среде подготовки: исходный PowerShell 7/C# interop ещё не проверен на пользовательской машине.
- CP53 проверяет native credential readback + child process respawn + bearer Google userinfo для 5 профилей. Это **НЕ** доказательство того, что Language Server действительно использовал новую учётную запись или что вызов модели прошёл. Не обозначать результат настоящим hot swap без независимой model identity/session continuity.
- Процесс прерывания дочернего Language Server может прервать текущую генерацию; запускать только в сознательно выбранный тестовый момент.
- Использовать только собственные/авторизованные Google учётные записи в пределах правил сервиса. Исходный CP-52B rollback не использовать.
- За один запуск выполняются 5 кандидатных переходов, а не 5 отдельно скачиваемых пакетов. Массовый import/patch не выполняется. Actions CI не запускались для этого docs-only commit.

## CURSOR
AG_pather / CP-52D PASS → CP-53 LIVE_5_ACCOUNT_EXPERIMENT_PREPARED → RECEIVE_CP53_RESULT → CP-54 MODEL_CONTINUITY_AND_ROLLOUT_DECISION.
