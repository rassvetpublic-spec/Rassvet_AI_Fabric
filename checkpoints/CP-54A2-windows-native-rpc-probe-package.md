# CP-54A2 — один Windows-only read-only тест локального Language Server RPC

Дата: 2026-10-10. Ветка: AG_pather.
Статус: PACKAGE_BUILT_STATIC_QA_PASS / RASSVET_DESKTOP_EXECUTION_PENDING.

## Основание
- CP-54A1: независимый от AG-tools минимальный `native_rpc.py` и 16 synthetic тестов; [Windows CI success](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38025855638) для `1b9f7385178ca23aef60fa080d0fccf57d2632b4`.
- Патченный реальный `language_server.exe` содержит protobuf метод `HasAuthToken` c bool `has_token`, `GetAuthStatus` c `auth_result` и скрытым внутренним localhost RPC. Метод `GetAuthStatus` потенциально показывает результат пропатченного hasValidAuth gate; флаг **не является** доказательством действительной провайдерской сессии.
- До запуска на Windows неизвестно, доступен ли Connect-v1/HTTP endpoint указанной сборки и как именно он защищён CSRF.

## Комплект
- `RAiF_AG_CP54A2_LocalRpcReadOnly.zip`, SHA-256 `69B2EFA1536317FA3ED8FEB6464F27588073F3AF0FF4DD24AF43645437A73840`; 3774 bytes; строго `probe.ps1` + `README.txt`; CRC pass.
- `RAiF_AG_CP54A2_Run.ps1`, SHA-256 `E2F95AD28E466F806835EECD33922304DA943492E4DD6177C82E0849704B1113`; ASCII-only; pinned ZIP SHA-256 проверяется до извлечения.
- `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP54A2_Run.ps1"`
- Staging `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP54A2_<id>`; конечный результат **непосредственно в корне** `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP54A2_RESULT_<id>.zip`.

## Что делает один прогон
1. Проверяет PowerShell 7, проектный каталог, ZIP integrity.
2. Read-only Get-Process: требует ровно один LS process для RPC, фиксирует PID+StartTimeUtc.
3. Read-only Win32_Process CommandLine получает in-memory CSRF из `--csrf_token` или `--csrf-token` (если присутствует). Полная командная строка, CSRF, header value никогда не выходят в логи/архив.
4. Get-NetTCPConnection определяет только IPv4-loopback/any IPv4 listening ports, принадлежащие **этому же LS PID**; максимум 4.
5. При доступном CSRF выполняет ограниченный локальный POST только на `127.0.0.1`: `HasAuthToken`, а после успешного ответа `GetAuthStatus`. Поддержка Connect JSON v1 — гипотеза до host-probe. `-NoProxy`, `-MaximumRedirection 0`, `-TimeoutSec 2`, only empty body. Реальный LS может при статусном RPC сам инициировать внутренний запрос; прямых облачных вызовов от скрипта нет.
6. Разбирает ответы только в оперативной памяти и публикует boolean `has_token_reported`, `local_auth_flag_untrusted` и коды доступности методов; не сохраняет project_id, email, raw response, токены.
7. Сравнивает PID и время создания LS после probe. Не трогает Windows Vault, native CredMan, бинарник, процессы, 9 аккаунтов, Google API, OAuth refresh или квоты.
8. Возвращает `STEPS.jsonl` со всеми стадиями launcher+probe, `RECEIPT.json`, `STATUS.txt`, `SUMMARY.txt`, `report.json` в RESULT ZIP. `SUCCESS` означает успешную диагностику — **не** то, что RPC работает. RPC availability и ошибки помечаются внутри report.json.

## QA
- Проверены ZIP CRC, 2 файла, закреплённый SHA-256, именование папок, отсутствие Credential Manager write/delete, taskkill/stop-process и внешних URL.
- PowerShell AST и настоящий RPC пока не прогонялись на Windows: Windows runtime PASS **не заявлен**. При ошибке launcher должен выдать safe stage/error, без секретов.
- Не выполнять реальную смену аккаунтов на этой стадии; hot-swap, поддерживаемый session reload и фактическая identity пока НЕ доказаны.
- ZIP/PS1 передаются как вложения в разговор, **не** публикуются в GitHub и не вызывают CI.

## CURSOR
`AG_pather / CP-54A1 CODE_WINDOWS_CI_SUCCESS → CP-54A2 LOCAL_RPC_PROBE_PACKAGE_READY → CP-54A2 RECEIVE_RESULT_ZIP → CP-54B SUPPORTED_SESSION_RELOAD_GATE`.

## Параллельная ветка RAI-FABRIC/10.1A
- GitHub trees readback: `10.1A` включает `10.1` и оба FF относительно `main`; дополнительные пути 10.1A не пересекаются с изменёнными AG_pather. Между main и AG_pather четыре общих изменённых файла, а не только три: `.gitignore`, ROADMAP, demo, run-tests. Никаких merge/push main. Далее отдельный временный worktree + Windows QA.
