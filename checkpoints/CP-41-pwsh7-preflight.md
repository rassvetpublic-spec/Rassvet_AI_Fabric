# CP-41 — исправление запуска CP-40 под PowerShell 7

Дата: 2026-10-10. Ветка: AG_pather.
Статус: SOURCE_PREPARED / SYNTHETIC_PYTHON_TEST_PASS / PWSH7_RUNTIME_UNVERIFIED.

## Входной результат
- Получен RAiF_AG_CP40_RESULT_20261010_044847_e459006c.zip.
- SHA-256 итогового ZIP: f1c75d9691bd876201f049b4f0ab4437a0194280c29f3df34fd75071c21ab1ec.
- CRC успешно проверен; файлы внутри: STATUS.txt, SUMMARY.txt, RECEIPT.json; report.json отсутствует.
- RECEIPT: protocol RAIF_AG_CP40_SAFE_READONLY, status FAILED_SAFELY, exit_code=2, reason UNKNOWN_RUNNER_ERROR.
- source_zip_sha256_verified=true, source_zip_candidates_found=1, output_location=project_root.
- Значения actual credentials и процессы Antigravity этим запуском не менялись, согласно отчёту.
- Из-за отсутствия report.json невозможно утверждать, что проверка аккаунтов, процессов и бинарника прошла. Точный сбой старого запускатора не установлен.

## Исправленная версия CP-41
- Требуемый хост: PowerShell 7 (pwsh.exe), а не Windows PowerShell 5.1.
- Пользователь скачивает ZIP и PS1 в D:\ЗАГРУЗКИ.
- ZIP RAiF_AG_CP41_WinPreflight.zip, SHA-256: 8E8536BD5127107EECC0868A330A8B5458E5A1DBEE45026F7E7F5EFF255D0CC1.
- PS1 RAiF_AG_CP41_Run.ps1, SHA-256: 595308EF670E18805F70B2123E4077BC379AC10210BA601674EBE6E0E0B56EDA.
- Команда: pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\RAiF_AG_CP41_Run.ps1"
- ZIP выбирается по известному имени (разрешаются (1), (2), ...), только рядом с PS1; проверка SHA-256 обязательна.
- Выполнение Python probe перенесено на System.Diagnostics.ProcessStartInfo.ArgumentList без shell quoting, с подавлением stdout/stderr (не сохранять секреты).
- В RECEIPT.json добавлены failed_or_completed_stage, safe_exception_type, powershell_version_major, python_exit_code; exception message и персональные пути не передаются.
- Внутренний staging: C:\GIT\Rassvet_AI_Fabric\_RAIF_RUNTIME\CP41_<id>.
- Результат сохраняется ПРЯМО в корне: C:\GIT\Rassvet_AI_Fabric\RAiF_AG_CP41_RESULT_<id>.zip.
- Allowlist содержимого: RECEIPT.json, STATUS.txt, SUMMARY.txt, report.json (только при успехе).
- Нет импорта, сетевых запросов, изменения токенов, Credential Manager, бинарников или процессов.

## Тесты
- ZIP CRC success, pinned ZIP SHA-256 соответствует содержимому PS1.
- Синтетический запуск Python probe: exit=0, accounts count=1, никакие синтетические email/token не попадали в report.
- Исполнение PS1 на целевой Windows/Pwsh7 ещё не подтверждено — следующий контрольный файл должен показать этап или SUCCESS.
- Исполняемые вложения остаются только в разговоре, не публиковались в GitHub.

## Курсор
AG_pather / CP-41 CORRECTED_PACKAGE_READY → CP-42 RECEIVE_PWSH7_RESULT_ZIP → CP-43 LOCAL_ACCOUNT_POOL_VALIDATION.
