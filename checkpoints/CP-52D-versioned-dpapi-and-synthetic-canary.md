# CP-52D — новый верифицируемый DPAPI-снимок и синтетическая проверка Credential Manager

Дата: 2026-10-10. Ветка `AG_pather`.
Статус: `BUILD_STATIC_PASS / WINDOWS_PWSH7_RUNTIME_PENDING`.

## Основание
- CP-52C: `SNAPSHOT_DIFFERS_FROM_STABLE_NATIVE`; DPAPI CurrentUser старого CP-52B снимка успешно раскрыт в памяти, но blob текущего `gemini:antigravity` отличается, два последовательных чтения native credential согласуются.
- Старый CP-52B emergency RestoreNative остаётся **ЗАПРЕЩЁННЫМ К ИСПОЛЬЗОВАНИЮ** в этом состоянии.
- Код CP-52C также содержал коллизию `$Status` / `$script:Status` и положил статус в ZIP под именем `SUCCESS` вместо `STATUS.txt`; в CP-52D используются `$StatusFile` и `$script:RunState`.

## CP-52D: один согласованный этап
1. Пользователь явно запускает PS7 с `-ConfirmNewSnapshot`; без флага не пишет snapshot.
2. Только локально считывает native `gemini:antigravity` через CredReadW. Проверяет базовый формат v2 без вывода токенов или email.
3. Сначала выполняет синтетический in-memory JSON/Base64 roundtrip и in-memory roundtrip реального blob **без логирования или экспорта содержимого**; комментарий и alias канонизируются для null/empty. Отдельно проверяет ProtectedData CurrentUser seal→unseal.
4. Создаёт **новый** файл `%LOCALAPPDATA%\RAiF\AGSupervisor\rollback\cp52d-native-credential-v2.dpapi` под ограниченными ACL. Старый CP-52B файл не изменяет и не удаляет. Новый файл никогда не перезаписывается: при повторном запуске — readback и сравнение, fail-closed при устаревших данных.
5. Читает новый зашифрованный файл с диска, расшифровывает в памяти и сравнивает сохранённые байты с native оригиналом, затем читает native второй раз и проверяет стабильность.
6. В том же запуске создаёт **только синтетический** Credential Manager generic target с префиксом `RAiF_AG_CP52D:canary:` + GUID, проверяет Win32 CredWriteW/ReadW/DeleteW, удаление подтверждает отдельным чтением; аварийная очистка в finally при сбоях.
7. Запрещает CredWriteW или CredDeleteW target `gemini:antigravity` программным ограничением внутри C# interop. Не перезапускает Antigravity, не меняет native target, не выполняет OAuth, модельных запросов и переключений.
8. Создаёт `STEPS.jsonl` на каждом этапе и строго allowlisted RESULT ZIP: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json; без email/token/blob и DPAPI backup.
9. `SUCCESS` означает новый проверенный encrypted snapshot плюс синтетическое Win32 восстановление лишь собственного canary. **НЕ означает** доказанное восстановление нативной Standalone авторизации и не является разрешением live-switch.

## Доставка и SHA-256
- `RAiF_AG_CP52D_VerifiedSnapshot.zip`: SHA-256 `E28DC34E69BAF55E2CFB00586AB03A000D73C12890452D89CE43CF707597ECF1`.
- `RAiF_AG_CP52D_Run.ps1`: SHA-256 `A2FD41399DC29D9F41AA6DD22EB5B2FFA692D58B27C0044045DD8F50ED931168`.
- ZIP и PS1 выдаются пользователю отдельными вложениями в чат, не публикуются в публичный GitHub.
- Поместить в `D:\ЗАГРУЗКИ`. Запуск:
  `pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP52D_Run.ps1" -ConfirmNewSnapshot`
- Итог: `C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP52D_RESULT_<runid>.zip`.
- Staging в `C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP52D_<runid>`.

## Качество / ограничения
- Проверено **статически**: ZIP CRC; ровно probe.ps1 и README.txt; SHA-256 закреплён в ASCII-only PS1, нет сетевых/процессных команд; ограниченный синтетический target для записывающих Win32 функций; отчёт без credential bytes; отсутствие коллизии имени `$Status`.
- PowerShell 7 в среде подготовки отсутствует, **реальное исполнение на Windows пока не проверено**.
- Если probe сообщает failure, не запускать CP-53 и не использовать старый CP-52B restore; отправить только обезличенный RESULT ZIP.
- 60 секунд и 5 аккаунтов — ограничение последующего явно подтверждаемого теста переключения, не текущей подготовки.

## CURSOR
`AG_pather / CP-52C STABLE_NATIVE_DIFF → CP-52D VERIFIED_V2_BACKUP_AND_CANARY_PENDING → CP-53 APPROVED_LIVE_60S_5_ACCOUNTS (GATED)`.
