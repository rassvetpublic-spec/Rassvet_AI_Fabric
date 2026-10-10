# CP-53 — два live-запуска корректно остановились до каких-либо изменений

Дата: 2026-10-10. Ветка: AG_pather.
Основание: два полученных пользовательских результата CP-53 и скриншот Antigravity QA.

## ZIP / findings
- Первый `RAiF_AG_CP53_RESULT_20261010_063223_63f83915.zip`, SHA256 `a97f6ff3f7e5566b22bbe354b9c39da1b68320ebdb915fc8ebd2710222e77f55`, CRC OK.
- Второй `RAiF_AG_CP53_RESULT_20261010_063402_ccbb6d0e.zip`, SHA256 `6318574481e2086d446c74b1046abeda17180aa9a1c51ef911b0a51b53abafc4`, CRC OK.
- В каждом архиве строгие 5 файлов: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json.
- В обоих отчётах: FAILED_SAFELY; reason FEWER_THAN_FIVE_FRESH_MATCHES; exit_code=2; 38 событий STEPS.jsonl (19 start / 17 ok / 2 failed), сбой в этапе `match_five_fresh_agtools_accounts_to_nine_raif_vault_entries`.
- raif_vault_targets_found=9, agtools_fresh_profiles_found=0, matched_vault_to_agtools=0, account_slots_ready=0, slots_completed=0.
- snapshot_verified_before_test=true; live_attempted=false; native_credential_write_attempted=false; restore_attempted=false; original_native_restored=false; child_respawns=0; external_identity_checks_ok=0; full_app_restart_performed=false.
- Статус original_native_restored=false НЕ означает ошибку восстановления: исходные credentials ни разу не изменялись, recovery не требовался.
- Отсутствие пяти свежих кэшированных access tokens НЕ опровергает пользовательское подтверждение работоспособности девяти аккаунтов AG-tools. Refresh token и cached access token имеют разные сроки.
- Скриншот показывает, что Antigravity выполняет QA public GitHub repo, включая сравнение main/AG_pather. Выполнение задачи не прерывалось CP-53.

## Найденный недостаток CP-53
- Код `Read-ManagerAccounts` прочитывает только первый найденный AG-tools data dir с accounts.json и папкой accounts, отбрасывает профили без access_token, expiry_timestamp или при expiry<=current+85s; в журнале никак не различает эти причины.
- Первый найденный каталог не обязательно активный (конфигурация может иметь перемещённую data dir). Нулевой результат может означать устаревший кэш, иную структуру JSON, disabled, ошибку парсинга или неактуальный каталог.
- Попытка live-switch без определения причины фильтрации бессмысленна.
- Исправление: CP-53A проверит все разрешённые местоположения кэша, классифицирует число raw profiles, disabled/invalid/expired/missing token, отдельно vault matches without exporting secrets, и выдаст ближайшее доступное действие. Никакого повторного изменения Credential Manager до 5 свежих кандидатов.
- Не переиздавать refresh tokens и не копировать пользовательские секреты в GitHub/RESULT.

## Cursor
AG_pather / CP-53 FAILED_SAFELY_NO_NATIVE_CHANGE → CP-53A CACHE_AND_MATCH_DIAGNOSTIC → CP-53B SUPPORTED_FRESH_TOKEN_REFRESH → CP-54 CONTROLLED_60S_FIVE_PROFILE_TEST.
