# CP-54A4 R2 — реальный listener LS обнаружен; CP-54A5 HTTPS probe

Дата: 2026-10-10. Ветка AG_pather. Source of evidence: пользовательский Windows RESULT ZIP + статически проверенный ранее отправленный probe и независимые исходники CodexBar.
Status: CP54A4_RUNTIME_DIAGNOSTIC_PASS / LOCAL_TCP_CONFIRMED / CONNECT_RPC_UNVERIFIED / CP54A5_STATIC_PACKAGE_PREPARED.

## CP-54A4 R2 — загруженный результат
- Архив: RAiF_AG_CP54A4_RESULT_20261010_091021_dabd95d1.zip; размер 3232 байта; SHA-256 2c57b3ddc4b37a440150ea2a8673dd9f50fe2acaa8b117f3043ca68abfe81c6b; ZIP CRC PASS.
- Строгий состав: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json; статус SUCCESS / reason NONE / probe_exit_code=0 / source ZIP hash verified / PowerShell 7.
- **74** корректных события STEPS.jsonl (36 start, 38 ok; 0 warning/failed). Пауза теста ~3.9 сек. Runtime и результат расположены в D:\ЗАГРУЗКИ вне Git-клона.
- Обнаружено 2 Language Server, оба прямые дочерние процессы Antigravity, оба с доступными in-memory CSRF аргументами и стабильной идентичностью процесса (PID + start time). Без публикации значений CSRF или full cmdline.
- Instance slot 1 / PID 19972 / started UTC 2026-10-10T04:53:07.2098966Z: GetExtendedTcpTable обнаружил **1** принадлежащий ему IPv4 LISTEN порт, Get-NetTCPConnection подтвердил **1**, netstat показал 0. Комбинированный уникальный порт **1**, принадлежность перед RPC перечитана.
- Slot 1: HasAuthToken отправлен на проверенный socket, но вернулся **HTTP_NON_200** (числовой статус CP54A4 не сохранял); GetAuthStatus SKIPPED_NO_CONFIRMED_RPC_METHOD. Сам факт HTTP_NON_200 ещё НЕ означает ConnectRPC handshake.
- Instance slot 2 / PID 28260 / started UTC 2026-10-10T05:14:03.9419245Z: ни WinAPI, ни cmdlet, ни netstat не обнаружили IPv4 listener; IPv6 тоже 0; RPC не отправлялся. Значит второй LS не считается доказанным RPC endpoint.
- Aggregate: rpc_confirmed_instance_count=0, instances_with_listeners=1, instances_with_csrf_argument=2; verdict LISTENERS_FOUND_BUT_RPC_UNVERIFIED.
- Отчёт подтверждает отсутствие native credential writes, RAiF Vault access, process modifications, external Google provider calls от скрипта и возвращённых секретов. Реальная авторизация аккаунта и HOT_SWAP **не подтверждены**.

## Диагноз и внешний кодовый контекст
- Анализ фактически запущенного CP54A4 probe.ps1 показывает: URI http://127.0.0.1:<verified_owned_port>/exa.language_server_pb.LanguageServerService/HasAuthToken; Content-Type application/json, Connect-Protocol-Version=1, X-Codeium-Csrf-Token. Скрипт скрывал точный HTTP status как HTTP_NON_200.
- Независимое руководство CodexBar: https://github.com/steipete/CodexBar/blob/main/docs/antigravity.md — для локального Connect endpoint Antigravity используется **HTTPS** localhost с самоподписанным сертификатом; HTTP применяется отдельно к extension_server_port. Это третьесторонний reverse-engineered источник, НЕ официальный стабильный API.
- Статический protobuf реального загруженного language_server.exe подтверждает HasAuthTokenResponse field has_token / JSON name hasToken; следовательно parser CP54A4 соответствует бинарной схеме. Основная гипотеза отказа — HTTP направлен на HTTPS порт, но числовой статус не сохранился. Не считать гипотезу подтверждённой до следующего Windows RUN.

## CP54A5 — наименьшая проверка гипотезы
- Source package RAiF_AG_CP54A5_NativeHttpsReadOnly.zip, 6829 bytes, SHA-256 BD55338D9A5C563BC9D5AC1215A5E84C0693E8B9E9FACAB2798B745D3525F026; ZIP CRC PASS; exactly probe.ps1 and README.txt.
- Launcher RAiF_AG_CP54A5_Run.ps1, 11332 bytes, SHA-256 8260343B72F83C8C96AA168A8FFE95362BED101EA1B10508857CCF8EF0E33743.
- Изменения относительно реально успешно работавшего CP54A4_R2: 1) HTTP -> HTTPS исключительно для проверенного локального owned listener; 2) -SkipCertificateCheck для самоподписанного loopback сертификата (не для внешних адресов); 3) при не-200 писать только числовой HTTP_STATUS_NNN, без body; protocol/bundle names and checksum changed coherently.
- В остальном оставлены независимые исследования двух LS PID, свежая проверка process-start+socket ownership, только HasAuthToken и GetAuthStatus, CSRF только в памяти, ограничение 2 sec / 16KiB report body / no proxy/no redirect, журнал и strict secret-safe отчёт.
- Read-only, никаких новых OAuth endpoints, Credential Manager, AG-tools, Google API, binary patch, proc stop, автоматического AccountPool switch. No secrets/EXE in public GitHub, только этот aggregate checkpoint.
- В анализирующей среде ZIP CRC/SHA, дифф исходников, protocol/field schema, file glob, path allowlist и отсутствие мутаций проверены; PowerShell 7 runtime недоступен, потому Windows RUN PENDING.

## Operator (D:\ЗАГРУЗКИ)
- Скачать ZIP и PS1 в корень D:\ЗАГРУЗКИ.
- Одна команда: pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A5_Run.ps1"
- Runtime: D:\ЗАГРУЗКИ\RAiF_AG_CP54A5_RUNTIME_<runid>\; RESULT: D:\ЗАГРУЗКИ\RAiF_AG_CP54A5_RESULT_<runid>.zip.

## CURSOR
AG_pather / CP54A4_R2_LOCAL_PORT_CONFIRMED → CP54A5_HTTPS_CONNECT_RPC_READONLY → RECEIVE_SAFE_RESULT → G1_NATIVE_READONLY_RPC_VERDICT.
Fabric Core parallel cursor remains RAI-FABRIC/10.1B WINDOWS_HOST_ACCEPTANCE; no merge into main and no Tower mutation.