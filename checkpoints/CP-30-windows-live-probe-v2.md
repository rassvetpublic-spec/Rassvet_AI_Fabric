# CP-30 — автономный Windows Standalone probe v2 (ZIP + 1 PS1)

Дата подготовки: 2026-10-10
Основание: CP-29, пользовательский CP-28 RESULT без обнаруженных активных процессов Antigravity.

## Цель
Повторить только read-only диагностику при открытом Google Antigravity Standalone; уточнить версии установленных Antigravity.exe и language_server.exe (если найден), стабильность PID/времени старта, доступность Git и Git metadata.

## Входные файлы
Скачать отдельно, оба файла в D:\\ЗАГРУЗКИ:
1. RAiF_AG_CP30_WinProbe.zip
2. RAiF_AG_CP30_Run.ps1

Запуск (вручную после открытия Standalone):
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\\ЗАГРУЗКИ\\RAiF_AG_CP30_Run.ps1"

Внешний архив SHA-256: 1b83682f2825630a07a909d3b69b7e76f0ab6013bc7f11010951f9161c5ee365
PS1 launcher SHA-256: 525f38c929f7b71a0c37ff1cb3133f7697dbb8444956626edaf956ce50f0141d
Запускатор проверяет хеш ZIP до извлечения и запуска.

## Отличия CP-30 от CP-28
- Для CP-28 процессов не обнаружено: перед запуском CP-30 пользователь вручную открывает Standalone.
- Отдельно выводятся наличие, версия, размер и SHA-256 файла Antigravity.exe в ограниченном установленном каталоге (без абсолютного пути в отчёте).
- В пределах каталога установки Antigravity проводится read-only поиск максимум четырёх файлов language_server.exe; метаданные и SHA-256 только этих бинарников.
- Git ищется не только в PATH, но и в типовых Windows Program Files / C:\\Git местах; результаты содержат только класс пути, не полный путь.
- Проверяется наличие .git в C:\\GIT\\Rassvet_AI_Fabric независимо от доступности git.exe.
- Пустые два снимка процессов теперь дают null для флага стабильности, а не ложное true.

## Безопасность
- Только перечисление известных файлов и процессов, проверка присутствия имени credential target через cmdkey, Git metadata.
- Ни OAuth refresh/access token, ни email, ни пользовательские файлы, ни contents SQLite, ни process memory, ни сетевые данные не читаются.
- Никакого запуска/перезапуска/kill Antigravity. Не патчить language_server.exe.
- Сохранять только report.json, SUMMARY.txt, STATUS.txt, RECEIPT.json в результирующем ZIP.
- Все результаты в C:\\GIT\\Rassvet_AI_Fabric\\_RAIF_RUNTIME\\RAiF_AG_CP30_RESULT_<ID>.zip.
- PS1 Bypass применяется только к отдельному процессу. Повышенные права не требуются.
- Пакеты приложены в разговоре, в публичный репозиторий не копируются.
- Архив проверен локально по ZIP CRC, схеме и совпадению SHA-256 с загрузчиком. PowerShell на реальной Windows пока НЕ запускался.

## Следующий курсор
AG_pather / CP-30 PACKAGE_READY → CP-31 RECEIVE_RUNTIME_RESULT → CP-32 VERIFY_LS_INSTANCE_AND_AUTH_ARCHITECTURE.
