# RAiF 10.1 — изолированный Git worktree, офлайн-diff и независимое ревью

**Дата:** 2026-10-10. **Статус реализации:** `PARTIAL / WINDOWS_HOST_ACCEPTANCE_PENDING`.
**Предыдущий checkpoint:** `checkpoints/RAI_FABRIC_10_0B_FIRST_LIVE_TURN_WINDOWS_VERIFIED_2026-10-10_R1.json`.
**Исходный commit main:** `b18f31cb39bd655c7fd7e50466069f23d29c957a`.

## 1. Что реализовано, без повторения модели

Отдельный модуль `src/rai_fabric/worktree_review.py` и Windows PowerShell-запускатор `scripts/demo-worktree-review.ps1` создают worktree по **полной локальной Git SHA-1**, собирают только разрешённые изменения, записывают читаемый `REVIEW.patch`, локальные SHA-256, `STAGES.jsonl` и `CHECKPOINT.json`. Никакого `codex.exe`, turn/start, модели, сетевого запроса, Git fetch/push/merge, автоматического merge или внешнего test runner нет. Разрешение на предыдущий успешный Codex turn не возобновляется. Права на запись в `CKS`, `RULESHUB`, `CONTROL TOWER`, `BPR40` и другие подсистемы не выдаются.

Офлайн-демо создаёт **только синтетический** `sandbox_demo/arithmetic.py` (`def add(a,b): return a+b`) в новом worktree. Три независимые детерминированные проверки выполняются над *точно фиксированной строкой*, не над произвольным рабочим файлом пользователя. Произвольный код из worktree **никогда не исполняется** этим модулем. Обобщённая проверка изменений выдаёт `mock_tests_passed: 0`: внешние интеграционные тесты не подменяются mock-успехом.

## 2. Локальный запуск на Windows

Требования: Windows 10/11, PowerShell 5.1+, Python 3.11+, установленный `git.exe`, полный локальный Git-клон нужного коммита, каталог `%LOCALAPPDATA%` доступен для создания изолированного результата. Без установки зависимостей и сетевого доступа.

Из корня `C:\GIT\Rassvet_AI_Fabric`:

- **Синтетический offline mock:** `./scripts/demo-worktree-review.ps1 -Mode Demo -PinSha b18f31cb39bd655c7fd7e50466069f23d29c957a`
- **Подготовка чистого worktree:** `./scripts/demo-worktree-review.ps1 -Mode Prepare -PinSha <40-символьный-SHA-HEAD> -AllowPaths 'sandbox_demo/arithmetic.py'`. Затем оператор редактирует разрешённый файл **внутри `workspace`**, вне исходного клона.
- **Проверка изменений:** `./scripts/demo-worktree-review.ps1 -Mode Review -RunDir '<полный-путь-RAIF_10_1_xxx>'`.
- **Локальные тесты нового модуля:** `./scripts/run-tests.ps1`, либо `python -m unittest discover -s tests -p 'test_worktree_review.py' -v` при `PYTHONPATH=src`.

Запускатор передаёт `-I -B` Python, не меняет глобальные переменные среды. **Для успешного `Prepare` SHA должен в точности совпадать с текущим HEAD репозитория.** Если после публикации этапа основная ветка сдвинулась, используйте её фактический SHA, а не старый из документа. Убедитесь, что каталог результата находится вне клона. `RunDir` — путь из JSON-ответа `prepare/demo`.

## 3. Ограничения и защита

1. Worktree создаётся `git worktree add --detach <path> <pin>` **без fetch**. Git hook path перенаправлен в пустой каталог; запрещены Git lazy-fetch и UNC/SMB-диски для сохранения офлайн-границы. Запрещены `.gitattributes`, `.gitmodules` в pinned tree и непустой `.git/info/attributes` для минимизации риска исполнения checkout filter; отключены унаследованные глобальные Git config/системные конфиги, fsmonitor, sparse checkout.
2. Allowlist содержит **только точные относительные пути**. Запрещены `..`, абсолютные пути, NTFS streams, Win32 device names, `.git`, `.github`, `BPR40`, `CKS`, `RULESHUB`, `CONTROL_TOWER`, `ANTIGRAVITYDATA` и системные конфиги. Регистр на Windows учитывается при проверке коллизий.
3. Не допускаются symlink/junction/reparse point на любом участке пути, hardlink с числом ссылок более 1, изменения типа или режима файла, индекса Git (staged), удаление/переименование файлов, игнорируемые неизвестные файлы, бинарные и не-UTF-8 данные, управляющие символы и известные форматы секретов.
4. Лимиты: не более **12** разрешённых/изменённых путей, **128 КиБ** на файл, **384 КиБ** суммарно и **768 КиБ** на patch. Проверка повторного чтения защищает от части гонок во время ревью. Обнаружение шаблонов секретов — эвристика, не сертификация отсутствия секретов. Патч не следует публиковать до ручного просмотра.
5. `STAGES.jsonl` содержит только события с контролируемыми кодами, без Git stderr, stdout, исходников и учётных данных. `MANIFEST.json` защищён контрольной SHA-256 от случайных изменений: контрольная сумма **не является криптографической подписью** и не защищает от злоумышленника, который может переписать обе части.
6. Результат `PENDING_HUMAN_APPROVAL` означает «локальный diff прошёл предусмотренные проверки, нужен человек», **не** «approved», **не** «merged» и **не** готовность к пяти доменам. Не удалять `ONE_TURN_10_0_CONSUMED.json` и не запускать прошлый live-скрипт.

При блокировке `review` записывает `BLOCKED` в JSONL и новый checkpoint, не записывает `REVIEW.patch` с невалидными данными. Для расследования worktree **не удаляется автоматически**. В `prepare` ошибки до создания каталога не имеют своего checkpoint; запуск не меняет отслеживаемые файлы исходного клона; `git worktree add` регистрирует worktree в служебном каталоге `.git/worktrees` исходного клона.

## 4. Проверки и опровержения (BPR)

| Приёмочный критерий | Контрпример | Ожидаемое поведение |
| --- | --- | --- |
| Pin SHA | SHA не равен `HEAD` | `SOURCE_HEAD_NOT_PINNED`, нет worktree |
| Граница allowlist | `scratch/extra.py` в изменениях | `OUT_OF_ALLOWLIST`; patch не сохранён |
| Индекс | `git add` вместо работы с unstaged данными | `INDEX_MUTATION_BLOCKED` |
| Безопасность | секретный шаблон / бинарный файл | `POTENTIAL_SECRET_BLOCKED` / `BINARY_OR_FILE_SIZE_BLOCKED` |
| Неизменность истории | удаление tracked файла | `UNSUPPORTED_GIT_CHANGE` |
| Ресурсы | файл больше 128 КиБ | `FILE_SIZE_LIMIT` |
| Integrity | изменение MANIFEST без пересчёта SHA | `MANIFEST_INTEGRITY_FAILURE` |
| Checkout hook/filter | `.gitattributes` в pinned Git tree | `CHECKOUT_ATTR_OR_SUBMODULE_BLOCKED` |
| Без ложной аттестации | произвольный файл содержит `raise` | код не исполняется; `mock_tests_passed: 0` |

Добавлены 20 Windows-only тестов в `tests/test_worktree_review.py`; статический разбор AST пройден. **Windows host-тесты фактически не запускались**: канал Remote Desktop Commander заблокирован месячной квотой. Новый GitHub Actions запуск для данного этапа **не создавался**; при публикации через отдельную ветку без PR существующая CI-конфигурация не должна запускаться. Статус хостовой приёмки остаётся `NOT_RUN`, несмотря на ранее зафиксированные 213 тестов предыдущего коммита.

## 5. Курсоры

- `10.1 — SAFE_WORKTREE_DIFF_REVIEW_OFFLINE`: исходник, PS1, 20 позитивных/негативных сценариев, журнал и checkpoint подготовлены.
- `10.1B — WINDOWS_HOST_ACCEPTANCE`: запустить только локальные команды на Windows; сверить SHA/diff/аудит, отказы, изоляцию и реальный счётчик tests. Нет разрешения на Codex turn.
- `10.2 — HUMAN_GATE_THEN_REVIEWED_TASK`: после независимого Windows PASS и явного согласия на следующий модельный turn; отдельно запрещены автоматическая промоция в canonical source и merge без оператора.

Сверка протокола BPR40: прочитаны Bootstrap R1 и `bpr_mode.md` из подключённого Google Drive. Контрольные SHA router/CORE/MANIFEST на компьютере не проверены из-за отсутствия прямого доступа к Windows; это **не означает полную активацию доверенной BPR40-цепочки**. Код этого этапа не зависит от полномочий BPR40 и не меняет внешние башни.
