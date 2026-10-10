# Rassvet AI Fabric — PLAN 10.1A–10.1D / BPR:PLAN ++ --

## R2 — контроль курса, исправления и защита pin (2026-10-10)

**Статус:** `PASS_STATIC_ONLY / WINDOWS_NOT_RUN`. Это новая версия плана после состязательного review bootstrap-скрипта, а не закрытие Windows QA. Базовые шаги ниже сохраняются и остаются обязательными.

1. **Разделение веток:** целевая ветка `raif-10-1-worktree-offline-20261010` и закреплённый SHA `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0` остаются **неизменными**. Исправленный запускатор R2, сценарий статической QA и этот план размещаются в отдельной `raif-10-1a-clone-handoff-20261010`. Добавление bootstrap в целевую ветку перед clone сдвинуло бы HEAD и сломало pin.
2. **Проверка уже существующего каталога:** обычный `git status --porcelain` не показывает ignored-файлы. R2 проверяет и `git ls-files --others --ignored --exclude-standard`. Если есть исключённые файлы, возвращается `EXISTING_IGNORED_CONTENT_PRESENT`; папка не очищается, ZIP/архивы не теряются.
3. **Reparse и Git-ссылка:** перед чтением существующего репозитория проверяются сама папка, `.git` и `.git/config`; смешанный или перенаправленный worktree нельзя объявить валидным.
4. **Не исполнять непроверенное содержимое:** перед checkout анализируется полный `git ls-tree`: только обычные Git blob-моды `100644` и `100755`; symlink/gitlink, `.gitattributes`, `.gitmodules`, неканонические Windows-имена, регистронезависимые дубликаты и более 3000 файлов блокируются.
5. **Повторный контроль pin:** после staging clone и перед переносом выполняется `git ls-remote --heads origin` и сравнение с 40-символьным SHA. Это снижает риск промежуточного branch drift, но не устраняет последний TOCTOU-интервал: дополнительный push после readback нельзя исключить.
6. **Надёжность evidence:** `CURSOR.json` и `CHECKPOINT.json` пишутся во временный файл с последующей заменой в одном каталоге; `STAGES.jsonl` — append с write-through/flush. Сбой может оставить частичную строку JSONL, но не должен интерпретироваться как PASS.
7. **Приватность:** вместо реального `C:\Users\...` хранится путь аудита через литерал `%LOCALAPPDATA%`; staging фиксируется **basename**, а не полный путь. Ранее полученный R1-чекпойнт не переписывается.
8. **Корректный статус отказа:** попытка staging учитывается до `git clone` (даже если clone оборвался). Staging при сбое оставляется на месте для ручной сверки; новых автоматических retries, reset и cleanup не выполняется.
9. **Исключение скрытого запуска:** нет `Codex`, `Antigravity`, API inference, Git push, Git merge, GitHub Actions, LFS pull или post-checkout script; ноль новых модельных вызовов.
10. **Изолированный QA:** `QA-Clone-RaiF-10_1-Static-R2.ps1` использует штатный PowerShell Parser и проверяет базовые инварианты, но не клонирует. Для реальной приёмки после clone потребуется отдельно выполнить `scripts/run-tests.ps1` и `scripts/demo-worktree-review.ps1` на Windows.

**Этапные чеки:**

| Этап | Критерий | Допустимый курсор |
|---|---|---|
| 10.1A.0 | Review кода, remote tree, QA Issue #1 | `RAI-FABRIC/10.1A-CLONE_SCRIPT_HARDENING` |
| 10.1A.1 | Windows PowerShell Parser + read-only `-Apply` не используется | `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION` |
| 10.1A.2 | Clone: SHA и origin, clean status, отсутствуют ignored-файлы, локальные чекпойнты | `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE` |
| 10.1B | Целевые 20 тестов и полный Windows unittest/smoke | `RAI-FABRIC/10.1C-ADVERSARIAL_OFFLINE_REVIEW` |
| 10.1C | Negative/Destroyer и выявленные P0/P1 устранены | `RAI-FABRIC/10.1D-INDEPENDENT_QA_GATE` |
| 10.1D | Независимое QA, отдельное человеческое принятие | `RAI-FABRIC/10.2-HUMAN_GATE_THEN_REVIEWED_TASK` |

**Операционное ограничение:** Desktop Commander ранее вернул лимит использования с указанием не повторять вызовы до восстановления квоты. Поэтому запуск `-Apply` на компьютере в этой сессии **не выполнялся**. Удалённо клонировать GitHub-ветку на GitHub-hosted runner вместо пользовательского `C:\GIT\...` нельзя считать выполнением задачи.

---


**Дата:** 2026-10-10  
**Режим:** Windows-only; `BPR:PLAN` + улучшение (`++`) + разрушительная проверка (`--`); журналирование, checkpoint после каждого этапа, не наследовать PASS.  
**Входной checkpoint:** `RAI_FABRIC_10_0B_FIRST_LIVE_TURN_WINDOWS_VERIFIED_2026-10-10_R1.json` → `10.1 — SAFE_WORKTREE_DIFF_REVIEW_OFFLINE`.  
**Последняя реализация:** `RAI_FABRIC_10_1_SAFE_WORKTREE_OFFLINE_IMPLEMENTED_2026-10-10_R1.json`, статус `PARTIAL`.  
**Текущий операционный курсор:** `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION`.  
**Итоговый статус на момент плана:** `PARTIAL` — QA-источники и GitHub проверены, локальный clone и Windows QA не запускались.

## 0. Доказанные входы и явная граница доверия

| Объект | Pin / статус | Как интерпретировать |
| --- | --- | --- |
| GitHub | `rassvetpublic-spec/Rassvet_AI_Fabric` | Публичный Git-репозиторий; GitHub здесь не является SSOT BPR40 |
| Ветка реализации | `raif-10-1-worktree-offline-20261010` | Не выполнять merge/PR/CI автоматически |
| Точный HEAD ветки | `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0` | Основной pin для нового clone и тестов этапа 10.1 |
| HEAD `main` | `b18f31cb39bd655c7fd7e50466069f23d29c957a` | Историческая база 10.0B, **не SHA целевого clone** |
| Путь Windows | `C:\GIT\Rassvet_AI_Fabric` | Существование и содержимое на компьютере пока не проверены |
| QA | GitHub Issue #1, открыта | Отдельный интеграционный gate `main` ↔ `AG_pather` |
| 10.1 тесты | 20 тестовых методов в `tests/test_worktree_review.py` | Определены в коде; **Windows исполнение NOT_RUN** |
| 10.1 CI | 0 запусков для ветки по readback | Не инициировать ради доказательства clone |
| Код модели | Ранее завершён один Codex turn 10.0B | Новые `turn/start` и автоматический retry запрещены |
| Локальная BPR40 authority | Подключённый GDrive Bootstrap прочитан, локальные router/core pins не подтверждены | Не считать BPR40 полностью активированной; никакой записи в башни |

**Нормативные источники:** [QA Issue #1](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/1), [ветка](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/tree/raif-10-1-worktree-offline-20261010), [коммит реализации](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/commit/a0daf08375b70d202b3dc7b5ab51f894e87d9ae0), `AGENTS.md`, `docs/GITHUB_ACTIONS_BUDGET.md`, `docs/WORKTREE_DIFF_REVIEW_10_1.md`.

## 1. Прочитанный QA: матрица дефектов и корректирующих действий

| Приоритет | Наблюдение/контрпример | Корректирующее действие | Gate |
| --- | --- | --- | --- |
| P0/интеграция | QA #1 зарегистрировал `add/add` конфликт `tests/test_windows_vault.py` между старой `main` и `AG_pather` | В актуальном `AG_pather` уже найден `tests/test_supervisor_windows_vault.py` (переименование); всё равно выполнить **новую** безопасную симуляцию слияния и двойную Windows-регрессию до решения Issue #1 | Блокирует **слияние**, но не отдельный clone ветки 10.1 |
| P1/Windows | CP1251 / `UnicodeDecodeError` в subprocess у `tests/test_cli.py` | Выполнить тест без загрязнения локальной настройки и с `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`; исправлять обработку кодировок отдельным change + regression | Нельзя скрывать падение из-за локали |
| P1/Windows | `WindowsApps\python.exe` иногда представляет alias-заглушку (код 9009) | Проверка **реального** интерпретатора 3.11+ через пробный `-c`, включая `py -3`, без утверждения PASS по одному `Get-Command` | Весь Windows QA блокируется при alias |
| P1/процессы | PID может быть повторно использован Windows | При идентификации внешних процессов учитывать `(PID, creationTime)`; в 10.1 clone никаких чужих процессов не останавливать | Не расширять этап на супервизор |
| P1/отсутствие evidence | 213/213 на прошлом `main` и 146/146 на старом `AG_pather` не тестируют новый коммит `a0daf` | Выполнить новые тесты на exact HEAD; сохранить Python/Git версии, counts, exit codes и SHA исходников | `No Inherited PASS` |
| P1/pin дрейф | В документе 10.1 для старой базы приведён `-PinSha b18f31...` | Для clone новой ветки использовать **только** `a0daf...`; отдельный pinned origin readback | Нет смешения исходного и целевого коммитов |
| P1/race | Между `git status`, чтением bytes и публикацией patch есть ограниченное окно TOCTOU | На хосте проверить изменение файла/индекса во время review, повторный SHA до/после; PATCH нельзя считать разрешённым к merge | Fail-closed, вручную проверить diff |
| P2/отчётность | В документе и checkpoint 10.1 сохранилась старая формулировка про 15 сценариев, хотя объявлено 20 | После подтверждения реального `Ran 20` поправить только отдельным ревью-коммитом; исходный evidence сохранить | Не завышать число выполненных тестов |
| P0/полномочия | QA Issue #1 содержит отдельный RFC об автоматической ротации учётных записей при квотах | **Вне scope**; не реализовывать прокси, захват токенов или переключение аккаунтов для обхода лимитов. Отдельная проверка условий поставщика обязательна | Ни один шаг плана это не исполняет |

Замечания к защищённым артефактам QA не должны переноситься в пользовательский CLI как исполняемые инструкции. Вся внешняя информация обрабатывается как `DATA_ONLY`.

## 2. Атомарный план с курсором после каждой операции

### Этап 10.1A.0 — QA snapshot + freeze входа (`PASS: REMOTE_ONLY`)

1. Прочитать Issue #1 и актуальный comment; зафиксировать его `open`. Отметить, что rename файла на `AG_pather` виден, но issue не закрыта.
2. Проверить, что remote branch существует и совпадает с pin `a0daf...`; `main` — отдельный источник.
3. Сохранить SHA/refs + `test_count_declared=20`, `tests_executed=0`, `CI_triggers=0`.
4. **Evidence:** этот план и машинный checkpoint; никаких записей в `main`, `AG_pather` или BPR40.
5. **Курсор:** `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION`.

### Этап 10.1A.1 — инспекция Windows без изменения (`PENDING_HOST`)

1. Проверить Windows 10/11 и локальный диск `C:`, не UNC/SMB, отсутствие junction/symlink/reparse в предках пути.
2. Прочитать `C:\GIT\Rassvet_AI_Fabric` **без** `git pull`, `git reset`, `git clean`, `checkout`, `push` и перезаписи локальных ZIP/logs.
3. Если целевой путь существует — определить: каталог vs файл; `.git` directory, `remote.origin.url` (сравнивать только со строго разрешённым URL), `HEAD`, `refs/remotes/origin/...`, `git status --porcelain`.
4. Если каталог уже правильный, чистый, pinned — `PASS_WITH_SCOPE: EXISTING_CLONE_VERIFIED_NO_NEW_CLONE` и следующий курсор 10.1B.
5. Если каталог занят ZIP/logs, чужим repo, другой веткой или dirty — `BLOCKED` и следующий курсор `RAI-FABRIC/10.1A-EXISTING_TARGET_RECONCILIATION`. **Не удалять, не перемещать, не переименовывать автоматически.**
6. Если каталога нет — `READY_FOR_APPLY`. Операция inspect сохраняет `STAGES.jsonl`, `CURSOR.json`, `CHECKPOINT.json` в `%LOCALAPPDATA%\Rassvet_AI_Fabric\clone_audit\<run>`.

### Этап 10.1A.2 — clone + SHA-pin при свободном каталоге (`PENDING_HOST`)

1. Запустить подготовленный `Clone-RaiF-10_1-Safe-R2.ps1` с параметром `-Apply` **только** если путь отсутствует. Это явное разрешение текущей операции clone, не повторного модельного turn.
2. Запускатор использует `git clone --no-checkout --no-tags --single-branch` в уникальный соседний staging (`C:\GIT\.RAIF_CLONE_STAGE_<GUID>`), без частичного clone и без авто-подтягивания LFS. Разрешён только обычный HTTPS-fetch исходников из GitHub на **этом** этапе.
3. Изолировать `GIT_*` от вызывающей сессии, отключить глобальные hooks, fsmonitor, submodules, LFS smudge, prompts и credential-helper; repo checkout — только после проверки pinned remote branch.
4. Проверить `refs/remotes/origin/raif-10-1-worktree-offline-20261010 == a0daf...`, отсутствие `.gitattributes`/`.gitmodules`, провести `checkout --detach a0daf...` **только в новом staging**.
5. Сверить `HEAD`, `origin`, `status` и абсолютный корень. Затем атомарно переименовать staging в **точно** `C:\GIT\Rassvet_AI_Fabric`; если цель появилась в момент операции, `BLOCKED` без overwrite.
6. Провести новый readback в целевом каталоге: `HEAD` pinned, `status` пуст, origin разрешён, `.git` directory. Записать чекпойнт.
7. Не выполнять команд `git push`, `git merge`, `git pull`, `git reset --hard` или cleanup существующих каталогов.
8. **Курсор после PASS:** `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE`. При FAIL сохранить 10.1A или EXISTING_TARGET_RECONCILIATION.

### Этап 10.1B.0 — Windows baseline и кодировки (`BLOCKED до фактического запуска`)

1. Проверить точный HEAD/путь/версию `git`, `Python>=3.11`, PowerShell и Windows. Вручную проверить alias Python на WindowsApps/ошибку 9009.
2. Временно установить `PYTHONUTF8=1` и `PYTHONIOENCODING=utf-8` **только для дочернего тестового процесса**; восстановить прежние значения в `finally`.
3. Из нового клона запустить `./scripts/run-tests.ps1`, записать exit code, тесты/ошибки/skips, wall-clock время. Предыдущие **213** не считать новым PASS.
4. Критерий: тесты завершены на Windows; нет ошибок/неожиданных пропусков; строки ошибок не содержат секретов. Предпочтительны очищенные summaries и SHA логов.
5. При ошибке окружения (не найден Python, неправильно настроенная локаль) вердикт `BLOCKED_ENVIRONMENT`, а не «код QA PASS».
6. **Курсор:** `RAI-FABRIC/10.1B-WINDOWS_TESTS_VERIFIED` только при реальном выполнении; иначе остаётся `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE`.

### Этап 10.1B.1 — офлайн mock и worktree-review (`BLOCKED до фактического запуска`)

1. В том же pinned клоне выполнить `scripts/demo-worktree-review.ps1 -Mode Demo -PinSha a0daf...` — изоляция `%LOCALAPPDATA%/Rassvet_AI_Fabric/worktree_review` вне source.
2. Проверить `MANIFEST.json`, `CHECKPOINT.json`, `STAGES.jsonl`, `REVIEW.patch`, SHA-256, `worktree --porcelain`, отсутствие изменений tracked/untracked в исходном clone.
3. Проверить, что отработали **три синтетические операции**, но ни одного Codex `turn/start` или произвольного тестового кода не выполнялось.
4. `PENDING_HUMAN_APPROVAL` — корректный выход модуля review, **не** разрешение на merge. Старый маркер `ONE_TURN_10_0_CONSUMED.json` сохраняется.
5. **Курсор:** `RAI-FABRIC/10.1C-ADVERSARIAL_OFFLINE_REVIEW` только после доказанного local PASS_WITH_SCOPE.

### Этап 10.1C — Destroyer: негативные проверки и независимый review (`PENDING_HOST`)

1. Подменить SHA/branch, создать файл за пределами allowlist; убедиться в `BLOCKED` **до** публикации патча.
2. Проверить staged, rename, delete, бинарный файл, NUL, не-UTF8, длинный файл, отсутствующий manifest, некорректные JSON-поля, секретный шаблон, hardlink, junction/symlink, ignored-файлы.
3. Дублированные имена при Windows case-fold и reserved names (`CON`, `COM1`) должны блокироваться.
4. Проверить запрет checkout filters `.gitattributes`/`.gitmodules`, lazy-fetch и network filesystem; не расширять scope под результат теста.
5. Имитация параллельной правки должна помечать обнаруженные гонки как `BLOCKED`, без обещаний абсолютной TOCTOU-устойчивости.
6. Не запускать пользовательские `pytest`/`unittest` из изменённого worktree автоматически: review и execution разделены.
7. Перед выдачей verdict проверить полный `STAGES.jsonl` и `CHECKPOINT.json` на секреты (CWE-532), дублирующиеся ключи и корректный текущий cursor.
8. **Курсор после evidence:** `RAI-FABRIC/10.1D-INDEPENDENT_QA_GATE`.

### Этап 10.1D — QA gate, протокол и обратная передача (`PENDING_HOST`)

1. Независимо сравнить `actual_HEAD`, SHA256 исходников и отчётов, `git status`, изменение исходного клона (должно быть 0), журнал этапов и исходные чекпойнты.
2. Записать матрицу `P0/P1/P2` и явно разделить: `HOST_PASS`, `BLOCKED`, `NOT_RUN`, `REVIEW_PENDING`; нельзя переносить былые PASS из 10.0B на новую реализацию.
3. Для Issue #1 отдельно провести read-only dry merge анализ `main`/`AG_pather` и полное Windows тестирование **после** собственного разрешения, без фактического merge; никакого proxy для обхода квот.
4. Исправления P0/P1 вести отдельным review-коммитом в отдельной ветке, только с тестом регрессии; при коммите кодовых изменений прежняя QA-аттестация аннулируется.
5. **Курсор после QA ACCEPTED:** `RAI-FABRIC/10.2-HUMAN_GATE_THEN_REVIEWED_TASK` — только отдельное разрешение на новые модельные запросы, изменения пяти доменов и merge.
6. Пока Windows QA не завершён — корректный текущий курсор остаётся 10.1A (clone не подтверждён) либо 10.1B (clone подтверждён, тесты ожидаются).

## 3. BPR Destroyer — 10 обязательных отказов (до нового PASS)

| Код | Атака | Ожидаемый результат | Артефакт |
| --- | --- | --- | --- |
| NEG-01 | `C:\GIT\Rassvet_AI_Fabric` занят ZIP-файлами, не является Git-клоном | `BLOCKED`, никаких удалений или перемещений | `STAGES.jsonl` |
| NEG-02 | Git remote чужой / origin с токеном в URL | `ORIGIN_NOT_EXPECTED`, URL не выводить в лог | JSON checkpoint |
| NEG-03 | Repo HEAD/main vs pinned `a0daf...` | Никакого checkout существующего repo, `BLOCKED` | `CURSOR.json` |
| NEG-04 | Ветка GitHub сдвинулась во время clone | Отказ `REMOTE_HEAD_NOT_PINNED`, staging не становится target | staging + checkpoint |
| NEG-05 | Отказ питания/обрыв сети во время clone | `BLOCKED`, повтор не выполняется скрыто, source не тронут | checkpoint при запуске |
| NEG-06 | Junction/symlink в `C:\GIT` или workspace | `REPARSE_PATH_BLOCKED` | журнал |
| NEG-07 | Git-smudge/checkout hook/submodule из непроверенного дерева | Запрет выполнения; `CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED` | журнал |
| NEG-08 | Git считает файл за allowlist или staged | `OUT_OF_ALLOWLIST` / `INDEX_MUTATION_BLOCKED`, нет одобренного patch | worktree checkpoint |
| NEG-09 | Код модели/секрет/платный API-клиент появляется как побочный процесс | Стоп, `BLOCKED`, без ложного `PASS` | process/evidence review |
| NEG-10 | CI / кто-то сдвинул `main` или `AG_pather` после QA | Старый статус становится `STALE_EVIDENCE`, нужна новая pin-проверка | QA matrix |

## 4. `++` — оптимизация скорости, CI и стоимости

1. **Один clone** (без Git Actions), полный небольшой Git-репозиторий, не partial и без `git lfs pull`.
2. **Один источник pin:** SHA `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0`; не смешивать с SHA `main` и прошлым Codex checkpoint.
3. Вначале read-only inspect и статус; при существующей грязной копии не скачивать заново в тот же каталог.
4. Тесты в Windows локально: сначала 20 целевых тестов, затем полный `run-tests.ps1` один раз при отсутствии P0.
5. Записывать только summary, SHA и машинные enum-коды, не полные environment variables, stdout моделей или токены.
6. Не запускать GitHub Actions для clone/документации/чекпойнтов; один отдельный Windows workflow только при реальном изменении кода после локальной проверки и QA.
7. Не запускать новый Codex turn и не использовать платный API fallback. Никакого Linux/macOS job.
8. При отказе checkpoint сразу фиксирует конкретный следующий курсор; устранение проблем выполняется на основании логов, без случайных повторов.

## 5. Артефакты и точное правило успеха

**Запускатор:** `Clone-RaiF-10_1-Safe-R2.ps1`; без `-Apply` — inspect-only, с `-Apply` — clone при свободном target. Использовать в Windows PowerShell, не запускать от имени администратора без необходимости.

**Место логов на пользовательской машине:** `%LOCALAPPDATA%\Rassvet_AI_Fabric\clone_audit\RAIF_CLONE_10_1_<UTC>_<id>\` (файлы `STAGES.jsonl`, `CURSOR.json`, `CHECKPOINT.json`). Каждый этап пишет новый cursor, а не молча идёт дальше.

**Минимальный PASS clone:** путь существует, нормальный Git clone ожидаемого репозитория, полный exact HEAD SHA `a0daf...`, origin совпадает, `status` чист, новое staged место больше не используется. Если каталог уже был корректным, PASS означает **проверенное использование существующего**, не новый clone. 

**Минимальный PASS Windows QA:** исполнены новые Windows-only tests на точном SHA, 20 целевых сценариев действительно отработали (не 20 skipped), проверены три synthetic tests, checksum/log/allowlist/diff, нет новых модельных вызовов, нет незарегистрированных изменений исходного клона. Не считать `PENDING_HUMAN_APPROVAL` автоматическим человеческим approval.

**Текущий честный verdict:** `PARTIAL / HOST_CLONE_NOT_VERIFIED / WINDOWS_TESTS_NOT_RUN`.  
**Следующий курсор:** `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION`; после подтверждённого clone → `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE`.
