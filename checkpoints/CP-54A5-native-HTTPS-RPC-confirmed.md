# CP-54A5 — подтверждён HTTPS ConnectRPC Language Server

Дата: 2026-10-10. Ветка AG_pather. Доказательство: загруженный пользовательский Windows-result `RAiF_AG_CP54A5_RESULT_20261010_091840_ed8acba7.zip`.

## Источник и целостность

- Размер 3204 bytes; SHA-256: `1e697f3f55677b8fce240a247cb25126007540829540290c851ed7eeacfd227f`; ZIP CRC OK; allowlist: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json.
- Receipt: `RAIF_AG_CP54A5_MULTI_LS_HTTPS_READONLY`, SUCCESS / reason NONE / exit_code 0 / probe_exit_code 0 / pinned ZIP hash verified / PowerShell 7 / result_location downloads_root.
- STEPS: **74** valid events, **36 start / 38 ok / 0 warning / 0 failed**, max elapsed 4818 ms.

## Что доказано

- Два экземпляра `language_server.exe`, PID 19972 (direct Antigravity parent, started UTC 2026-10-10T04:53:07.2098966Z) и PID 28260 (direct parent, started 2026-10-10T05:14:03.9419245Z); оба стабильны до/после.
- Slot 1 PID 19972: собственный IPv4 listening порт обнаружен через GetExtendedTcpTable, ровно **1** подтверждённый порт, отдельный CSRF аргумент присутствует в памяти. HTTPS localhost Connect-v1: **HasAuthToken OK** и **GetAuthStatus OK**. `has_token_reported=true`, `local_auth_flag_untrusted=true`.
- Slot 2 PID 28260: подтверждённого IPv4 (или IPv6) слушателя нет; RPC не вызывался. `SKIPPED_NO_VERIFIED_TRANSPORT` **не равен** неверной авторизации или неисправности.
- `aggregate.rpc_confirmed_instance_count=1`, `verdict=READONLY_NATIVE_RPC_CONFIRMED`.
- Нет изменений credentials, RAiF Vault, процессов; скрипт не отправлял внешних Google запросов и не экспортировал значения токенов.

## Граница доказательства

- Локальный HTTPS API подтверждён в установленной сборке, **не является официальным гарантированным стабильным API**.
- `GetAuthStatus.hasValidAuth` не независимое подтверждение авторизации, так как бинарник ранее модифицирован CP-31; нет provider proof, active-account identity proof, live account switch или stream continuity proof. Все соответствующие report flags остаются false.
- `GetAuthStatus` и `HasAuthToken` подтверждают работу локального HTTPS транспорта и штатных RPC-методов; нельзя выводить пригодность OAuth 9 аккаунтов и hot switch.

## Исправление Python core CP-54A5

- `native_rpc.py` исправлен с HTTP на **HTTPS** loopback на основании Windows evidence; внутренний Python клиент ранее использовал неподтверждённый HTTP.
- CA-check допускается пропустить только для фиксированного IP `127.0.0.1` с самоподписанным TLS-сертификатом. Не создавать global unverified SSL state, не принимать внешний host, proxy или redirect. Выбор PID+process-start+владения TCP портом — обязательная ответственность будущего Windows observer до использования этого низкоуровневого клиента.
- `tests/test_native_rpc.py` обновлён для TLS и дополнен отрицательными тестами redacted transport exceptions. Только synthetic / no external network / no user secrets.
- CP-54A5 code commit инициирует один штатный Windows CI; до readback CI кодовая реализация отдельно не маркируется как Windows PASS.

## План следующего этапа

**CP-54B / безопасный quota observer:** использовать проверенный локальный HTTPS канал для исследования разрешённых read-only методов `GetUserStatus`, `RetrieveUserQuotaSummary`; сериализовать только группы/окна/остатки/время обновления, не email/token/project/полные ответы. Метод квот может инициировать downstream provider запрос из LS, это не обязательно офлайн; живой тест отдельным opt-in.

**Cursor:** `AG_pather → CP-54A5_NATIVE_HTTPS_RPC_CONFIRMED → CP-54A5_PYTHON_CLIENT_HTTPS_CI → CP-54B_NATIVE_QUOTA_OBSERVER_DESIGN → ONE_USER_OPT_IN_WINDOWS_QUOTA_TEST`.
