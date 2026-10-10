# CP-54B1 — нативные квоты через HTTPS RPC, первый ограниченный опрос

Дата: 2026-10-10. Ветка AG_pather.
Статус: PACKAGE_BUILT_STATIC_QA_PASS / USER_WINDOWS_RUN_PENDING.

## Точка входа и предыдущие доказательства

- CP54A5 Windows RESULT `RAiF_AG_CP54A5_RESULT_20261010_091840_ed8acba7.zip`, SHA256 `1e697f3f55677b8fce240a247cb25126007540829540290c851ed7eeacfd227f`: 74 шагов, 0 предупреждений и ошибок; один HTTPS ConnectRPC endpoint обнаружен у LS PID 19972; `HasAuthToken=OK/true`, `GetAuthStatus=OK`. Второй LS 28260 без собственного подтверждённого listener, не опрашивался. Отсутствие CredMan/process writes подтверждено.
- `src/raif_ag_supervisor/native_rpc.py` переведён с HTTP на HTTPS localhost и протестирован: 18/18 офлайн synthetic PASS; Windows CI [run #38030732079](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38030732079) SUCCESS для коммита `748d9f7fa003e45a1f1ae7cf33004528886e5e46`.
- Из предоставленного реального `language_server.exe` бинарным парсингом FileDescriptorProto подтверждены: 324 метода LanguageServerService; GetUserStatusResponse содержит userStatus+planInfo; RetrieveUserQuotaSummaryRequest содержит request и forceRefresh; Google quota_summary.proto содержит groups / buckets / window / remainingFraction / disabled / resetTime. Это статический protobuf-контракт, а не доказательство заполненных квот активного профиля.

## Назначение CP54B1

Использовать **уже доказанный** HTTPS localhost канал, чтобы прочитать **один текущий сеанс** через методы `GetUserStatus` и `RetrieveUserQuotaSummary`, сохранив в результат только безопасные агрегаты. Никакого сканирования аккаунтов AG-tools, переключений или изменения авторизации.

ВНИМАНИЕ: `GetUserStatus` и `RetrieveUserQuotaSummary` могут инициировать **сетевое обращение самого Language Server к Google**. Поэтому опрос этих методов требует **явного пользовательского параметра `-AllowQuotaRead`**. Без параметра оба новых метода пропускаются, хотя два уже проверенных статусных RPC могут выполняться.

## Артефакты (в чат, не в публичный GitHub)

- `RAiF_AG_CP54B1_NativeQuotaReadOnly.zip`: 8391 bytes, SHA256 `BAAF18FAC18B3B9600BA6CF38DDBB54EF3B30597D273648A8C8AC438F8FECAD0`; ZIP CRC PASS; строго `probe.ps1` и `README.txt`.
- `RAiF_AG_CP54B1_Run.ps1`: 11450 bytes, SHA256 `3981779A851586F55BDFF0B5D5CBC546FE90EB9979466755CF72E4932F326B56`; pinned source ZIP hash, checks paths and schema, full stage logging.
- Запуск: `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54B1_Run.ps1" -AllowQuotaRead`.
- Runtime: `D:\ЗАГРУЗКИ\RAiF_AG_CP54B1_RUNTIME_<runid>\`.
- Result: `D:\ЗАГРУЗКИ\RAiF_AG_CP54B1_RESULT_<runid>.zip`.
- Git-клон `C:\GIT\Rassvet_AI_Fabric` — только чтение. Все RESULT/runtime исключительно в корне Загрузок, без создания файлов в репозитории.

## Что проверяет

1. Один Pass с максимум четырьмя отдельными LS PID. Для каждого — StartTime UTC, parent Antigravity, своя CSRF-строка только в памяти, три независимых источника IPv4 own-port и пассивный IPv6, свежая проверка port owner перед каждым RPC.
2. Первые методы `HasAuthToken` и `GetAuthStatus` по HTTPS/Connect-v1, как в CP54A5; для quota обязательны opt-in, свой подтверждённый listener и reported hasToken=true.
3. `GetUserStatus`: проверяется только наличие полей userStatus и planInfo (значения и email никогда не сохраняются).
4. `RetrieveUserQuotaSummary`: запрос `{"request":{},"forceRefresh":false}`, TTL/timeout до 2 сек, локальный ответ максимум 256 KiB (обрабатывается в памяти). Выводится только количество групп, безопасные идентификаторы gemini / claude_gpt и значения 5h/weekly remainingFraction 0..1, disabled boolean, нормализованный reset UTC при наличии.
5. Нераспознанные displayName/window не публикуются, обрабатываются как UNKNOWN; дубликаты групп/окон — `DUPLICATE_* / NOT_VERIFIED`, не фиктивная квота.
6. В RESULT только STATUS/SUMMARY/RECEIPT/STEPS/report. Никогда не включать raw HTTP body, токены, CSRF, email, project ID, userinfo, quota bucket descriptions или полную commandline.
7. Ни одна стадия не запускает модельный inference, не трогает native CredMan, RAiF Vault, бинарники, не останавливает процессы и не переключает аккаунты.

## Статическое тестирование

- ZIP CRC/hash, точные 2 члена, pinned SHA в launcher, совпадение протокола и поля quota_read_requested в отчёте/валидации PASS.
- Количество безопасных RPC-методов, allowlist флагов, фиксированный HTTPS 127.0.0.1, явный параметр `-AllowQuotaRead`, отсутствие внешних URL и mutating commands проверены.
- Статический баланс PowerShell delimiter-скобок PASS, но он **не** заменяет PowerShell AST и фактический Windows запуск.
- Runtime G1 quota method and response schema **NOT TESTED** до загрузки пользовательского RESULT ZIP.

## Влияние на остальные направления

- Мастер-план Fabric остаётся `10.1B WINDOWS_HOST_ACCEPTANCE`, разветвления main/AG_pather не сливались.
- Control Tower/BPR40 remains read-only: Drive authority, no GitHub-Tower sync/merge/activation.
- AG-tools, cached Google account tokens и неразрешённый reverse proxy не требуются.

## Следующий курсор

`AG_pather → CP-54B1 / EXPLICIT_NATIVE_QUOTA_RESULT → QUOTA_SCHEMA_AND_WINDOWS_VERDICT → CP-54B2 / OWNED_NATIVE_QUOTA_OBSERVER → CP-54C_GATE_ONLY_IF_APPROVED`.
