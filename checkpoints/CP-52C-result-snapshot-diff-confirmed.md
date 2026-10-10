# CP-52C — результат диагностики DPAPI / native credential

Дата: 2026-10-10. Ветка AG_pather.

## Входной артефакт и его целостность
- Получен `RAiF_AG_CP52C_RESULT_20261010_060805_dd37e1a7.zip`.
- SHA-256: `cd6a3593c35e0f40796f11af211e598c37d02323f3e30544e5f2023e3c70bb28`.
- ZIP CRC успешно проверен. Содержимое: `SUCCESS`, `SUMMARY.txt`, `RECEIPT.json`, `STEPS.jsonl`, `report.json`. **NB:** ожидаемый `STATUS.txt` ошибочно помещён как `SUCCESS` из-за коллизии переменной `$Status` (путь к файлу) и `$script:Status` (строка статуса) в PowerShell, где имена нечувствительны к регистру. Исправить в CP-52D.
- Receipt: `status=SUCCESS`, `reason=NONE`, `probe_exit_code=0`, `capability_verdict=SNAPSHOT_DIFFERS_FROM_STABLE_NATIVE`, `pwsh_major=7`, `bundle_verified=true`.
- STEPS.jsonl: 42 события (21 start + 21 ok), без ошибок выполнения.

## Факты сравнения
- Старый CP-52B DPAPI backup присутствует, успешно расшифровывается; схема валидна.
- Нативная запись `gemini:antigravity` успешно прочитана дважды с интервалом 120 ms, все поля совпали между чтениями.
- Старый снимок НЕ совпадает с текущей записью.
- Побайтовое совпадение blob=false; поля comment и alias=false; поля username, flags, type, persist, attribute_count=true.
- Различие comment/alias **может** быть объяснено нормализацией null в пустые строки при присваивании полям C# из PowerShell; это гипотеза по исходникам, не проверенный факт. Различие blob не объясняется таким сравнением и сохраняет главный блокер.
- По собственному отчёту скрипта native, encrypted snapshot и процессы не изменялись; никаких запросов к провайдеру и переключений не было.

## Инженерное решение
1. **Запретить использование CP-52B RestoreNative** для этого снимка; пригодность восстановления не доказана.
2. Не перезаписывать и не публиковать старый DPAPI файл.
3. CP-52D: новая версия snapshot, независимая строгая проверка синтетической сериализации и точного Base64/bytes, нормализация optional null/empty metadata, readback из нового DPAPI CurrentUser файла.
4. CP-52D может проверить запись/чтение/удаление только изолированной синтетической RAiF Credential Manager записи, но не native target. Для создания нового снимка требуется отдельное явно названное пользовательское подтверждение.
5. Перед будущим CP-53 нужно доказать, что новое сохранение и readback дают идентичный blob и 9/9 исходного RAiF Vault остаются неизменны.
6. Лимит будущего живого теста: 60 секунд суммарно, максимум пять профилей; пока ни один живой switch не запускать.

## CURSOR
AG_pather / CP-52C SNAPSHOT_DIFFERENCE_DIAGNOSED → CP-52D VERSIONED_DPAPI_SNAPSHOT_AND_CANARY → CP-53 OPT_IN_60S_FIVE_ACCOUNTS.
