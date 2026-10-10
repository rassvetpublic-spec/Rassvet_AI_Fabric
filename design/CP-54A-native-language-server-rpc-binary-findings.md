# CP-54A — статический анализ предоставленных Windows EXE: встроенный RPC вместо тяжёлого SessionAdapter

Дата: 2026-10-10. Ветка: AG_pather.
Статус: **STATIC_PROTO_DESCRIPTOR_VERIFIED / LIVE_RPC_NOT_TESTED / NO_SWITCH_PERFORMED**.

## Анализированные локальные файлы (не публикуются в GitHub)

| Файл | Размер | SHA-256 | Формат |
|---|---:|---|---|
| language_server.exe | 165675008 bytes | b23c730a3b23953a7e46851593a5013bc888c524c8965cbb21618fc51122d81e | PE32+ AMD64, Go 1.28 prerelease compiler |
| webm_encoder.exe | 13615104 bytes | dd52b4692efc73fa1c13a07c0ec0312822fbd583a9750e6a1db6c5e3e247e23f | PE32+ AMD64, Go 1.28 prerelease compiler |

SHA-256 language_server.exe **точно совпадает** с post-patch CP-31/33. Исполняемые файлы изучены исключительно статически, ни один из них не запускался и не модифицировался. webm_encoder.exe содержит внутренний build target `third_party/jetski/cortex/utils/mcp/encoder:webm_encoder`, видео/webm/VP9-подсказки; в пределах этого аудита он не является источником auth/session интерфейса.

## Доказательство: разобраны БИНАРНЫЕ protobuf дескрипторы, не просто текстовые строки

Для `language_server.exe` из внутренних serialized `FileDescriptorProto` извлечены стандартным protobuf-парсером:

- `third_party/jetski/language_server_pb/language_server.proto`: пакет `exa.language_server_pb`, сервис `LanguageServerService`, **324 RPC-метода**, 743 типов сообщений; сырой дескриптор начинается около file offset `0x35D8DA0`.
- `third_party/jetski/host_bridge_pb/host_bridge.proto`: пакет `exa.host_bridge_pb`, сервис `HostBridgeService`, **3 RPC-метода**, 8 типов сообщений; дескриптор около `0x31D7C0A`.
- HostBridge методы: `GetUpdateStatus`, `ApplyUpdate`, `GetOAuthToken`.
- `GetOAuthTokenResponse.token_info` — `OAuthTokenInfo` с полями `access_token`, `token_type`, `refresh_token`, `expiry`, `is_gcp_tos`. Это **геттер** от хоста; он не является доказательством внешней команды записи/подмены токена.
- `LanguageServerService` содержит `GetAuthStatus`, `HasAuthToken`, `LoginWithBrowser`, `Login`, `AuthLogout`, `JetboxSubscribeToOAuthState` (server-stream), `GetUserStatus`, `GetAvailableModels`, `RetrieveUserQuotaSummary`, `GetCapabilities`, `GetRemoteControlInfo`.
- `GetAuthStatusRequest` и `HasAuthTokenRequest` пустые. `GetAuthStatusResponse.auth_result` содержит `has_valid_auth`, `auth_mode`, granted_scopes и другие значения, но **после CP-31 локальный hasValidAuth gate патчен**, поэтому флаг нельзя принимать за независимое provider-удостоверение.
- `GetUserStatusResponse` содержит `user_status` и `plan_info`; `GetAvailableModelsResponse` содержит provider fetch response; `RetrieveUserQuotaSummaryResponse` содержит `google.internal.cloud.code.v1internal.RetrieveUserQuotaSummaryResponse`.
- `GetAvailableModelsRequest.force_refresh`; `RetrieveUserQuotaSummaryRequest.force_refresh` и provider request — методы могут инициировать downstream сетевые запросы, поэтому «локальный RPC» не обязательно «офлайн» или «без расхода».
- `LoginRequest` содержит `is_gcp_tos`, `additional_scopes`, `enable_business_login`, `wif_login_info`; **не содержит `access_token` или `refresh_token`**. `AuthLogoutRequest` пуст.
- Среди **всех 324 названий** нет точных RPC `SwitchAccount`, `SetAuthToken`, `ReloadCredentials`, `ReloadAuth`, `SetOauthToken`. Это не доказательство отсутствия альтернативного внутреннего механизма, но прямой опубликованный метод switching не найден.
- `GetCapabilitiesResponse` в разобранной версии содержит только `supports_hook_result_proto_bytes`; не является API получения capability карты переключения аккаунтов.

## Транспорт / границы подтверждения

В бинарнике есть пример пути `/exa.language_server_pb.LanguageServerService/<method>`, localhost и заголовка `x-codeium-csrf-token`. Эти строки рассматриваются **как артефакты**, а не как инструкции к исполнению.
Независимые третьесторонние документации CodexBar, PaceBar и OpenUsage описывают Connect-RPC v1 с локальным динамическим port, HTTPS/HTTP и CSRF. Это **не официальный стабильный публичный контракт**, работа конкретно на RASSVET_DESKTOP не проверена.

https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md
https://pacebar.io/docs/providers/antigravity

Важный риск: full cmdline LS может содержать CSRF / internal tokens; не включать её в лог/RESULT ZIP. Никогда не передавать CSRF/access/refresh tokens в GitHub или лог. Не вызывать mutating `Login`/`AuthLogout` как часть read-only discovery.

## Архитектурный вывод

**Отменить безусловную разработку большой самостоятельной системы SessionAdapter из старого CP-54A1.** Нужен небольшой и по возможности read-only **NativeRpcObserver / LocalConnectClient** для существующих методов (при подтверждении разрешённого доступа и runtime). Это транспортная обёртка, а не новый OAuth/profile manager.

Отдельный `SwitchController` / RecoveryEngine проектировать **только после** документирования безопасного и поддерживаемого способа выполнить смену активной сессии. Credential Manager readback, HostBridge.GetOAuthToken и Login/Logout не подтверждают hot swap. Если такой способ не найден, конечный продукт способен делать read-only статус/квоты, наблюдение и согласованный user-controlled handoff с checkpoint/resume, но не фиктивный no-restart switch.

## Новый план / STOP-GO

**CP-54A1:** выполнить один **read-only локальный** Windows PowerShell 7 RPC discovery: подтвердить dynamic localhost endpoints + Connect version, без публикации CSRF, PID+creation marker, `GetStatus`/`HasAuthToken`/`GetAuthStatus` и `GetUserStatus`, только если интерфейс допустим; тайм-ауты, no mutation. В отчёт только статусы, не полные ответы (план/email/quota могут быть личными).

**CP-54A2:** на основании результатов внедрить минимальный LocalConnectClient + safe quota extraction, при этом не использовать AG-tools. Граничный parser/маршрутизация только после runtime proof.

**CP-54B:** изучить, вызывает ли LS HostBridge.GetOAuthToken повторно при изменении auth state (без перехвата трафика и без изменения credential в read-only пакете). Установить, существует ли разрешённый механизм штатного смены пользователя без рестарта; иначе UNSUPPORTED/MANUAL_HANDOFF.

**CP-54C:** только после проверенного restore и 2-профильного gate — 5 профилей/60 секунд по явному согласию. Нельзя считать «пять RPC-ответов» пятью успешно переключёнными профилями.

**CP-54D–56:** checkpoint/recovery, Fabric integration, Windows QA. Сохранять policy в docs/PRODUCT_SCOPE.md: не автоматизировать обход квот/политик потребительских подписок.

## Курсор
`AG_pather / CP-54A STATIC_NATIVE_PROTO_VERIFIED → CP-54A1 READ_ONLY_LIVE_LOCAL_RPC_PROBE → CP-54A2 MINIMAL_NATIVE_RPC_CLIENT → CP-54B AUTH_SESSION_RELOAD_GATE → CP-54C TWO_THEN_FIVE_OPT_IN → CP-54D / CP-55–56`.

## Security/Integrity
Ни исходные бинарники (включая пропатченный EXE), ни содержимое native/RAiF credentials в GitHub не переданы. Статический аудит не подтверждает безопасность бинарников или официальную поддержку частного RPC.
