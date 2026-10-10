# RAiF 10.1B — локальная приёмка Windows без модели

Дата: 2026-10-10. Статус публикации: подготовлено к host QA, **реальный Windows запуск не подтверждён**. Исходный GitHub SHA: `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0`, ветка `raif-10-1-worktree-offline-20261010`.

## Цель

После безопасного clone в `C:\GIT\Rassvet_AI_Fabric` проверить **20 тестов** worktree review, полную регрессию и **3 синтетических проверки** на реальном Windows. Результаты записываются вне Git-репозитория: `%LOCALAPPDATA%\Rassvet_AI_Fabric\host_qa\RAIF_10_1B_*\STAGES.jsonl`, `CURSOR.json`, `CHECKPOINT.json`, `SUMMARY.json`.

Этот пакет находится в отдельной handoff-ветке. **Не вносить его в pinned-ветку**: любое изменение её HEAD сделает SHA pin невалидным.

## Порядок

1. При отсутствии подтверждённого clone сначала использовать `Clone-RaiF-10_1-Safe-R2.ps1` из предыдущего пакета. Без `-Apply` — только инспекция. С `-Apply` — только когда `C:\GIT\Rassvet_AI_Fabric` отсутствует. Существующий каталог никогда не удалять автоматически.
2. В Windows PowerShell 5.1 запустить `Test-RaiF-10_1B-Static.ps1`. Он проверяет PS1 Parser/AST и набор контрольных условий, ничего не клонирует.
3. Запустить `Verify-RaiF-10_1B-Windows.ps1` без параметров: только read-only preflight и проверка существующей копии, Git HEAD и SHA-256 трёх критических файлов. При успехе будет `READY_FOR_RUN`; тесты ещё не запускались.
4. Затем явно запустить `Verify-RaiF-10_1B-Windows.ps1 -Run`. Он выполняет (а) 20 целевых `unittest`, (б) полную регрессию `test_*.py`, (в) детерминированный офлайн-demo без Codex; после каждого шага повторяет проверку исходного клона.
5. Передать из папки нового run файлы `CHECKPOINT.json`, `CURSOR.json`, `SUMMARY.json`, `STAGES.jsonl` — **только после проверки, что в них нет персональных данных/секретов**. Не передавать `.git/config`, `%APPDATA%`, `auth.json`, OAuth и сырые stdout/stderr. 

## Gates и остановка

- Если clone отсутствует или каталог занят другим содержимым: `BLOCKED`, курсор `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION` либо `10.1A-EXISTING_TARGET_RECONCILIATION` согласно clone-скрипту.
- Если есть Python WindowsApps alias, неподходящая версия Python, неправильный Git remote/pin, скрытые index flags (`assume-unchanged`, `skip-worktree`), игнорируемые файлы или несовпадение SHA-256 исходников: `BLOCKED`; тесты не выполнять.
- Тесты требуют точных `20/20`, `0 skips`; полный suite — `0 errors/failures` и `0 skips`. Skip из-за отсутствия прав на symlink остаётся `BLOCKED` (не скрывать skip).
- Офлайн mock должен закончиться `PENDING_HUMAN_APPROVAL`, 3 синтетических проверки и корректный SHA `REVIEW.patch`. Это **не** разрешение на merge.
- При зависании или ошибке дочернего процесса: `BLOCKED`; запускатор останавливает только известный родительский PID, но **не гарантирует уничтожение всех потомков**. Нельзя считать cleanup PASS без дополнительного Windows Job Object gate.
- Никаких Codex `turn/start`, оплатного fallback, обращения к токенам, пушей, merge и GitHub Actions. Потребление средств/квоты внешними процессами отдельно не измеряется.

## BPR:++ / --

`++`: один исходный clone, один запуск полной регрессии, локальный mock, bounded memory/timeout, только sanitised summary.

`--`: 20 негативных/позитивных тестов не заменяют отдельный независимый review. Fail-closed при отсутствующем pin, изменённом tracked файле, скрытых Git-index flags, skipped tests, секретах в патче, отсутствии checksum/cursor. Факт полного тестового набора подтверждается только Windows evidence.

## Ожидаемый checkpoint и курсор

- До host clone: `RAI-FABRIC/10.1A-CLONE_PREFLIGHT_AND_QA_RECONCILIATION`.
- После подтверждённого clone, до тестов: `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE`.
- После всех локальных тестов и mock: `RAI-FABRIC/10.1C-ADVERSARIAL_OFFLINE_REVIEW`; итог `PASS_WITH_SCOPE`, но **не** окончательное принятие этапа 10.1D.

## Учёт QA Issue #1

Слияние `main` и `AG_pather` — отдельная задача. Текущая локальная QA ветки 10.1 не подтверждает совместимость этих двух веток. Решение владельца об изменении внутренней архитектуры считается принятым на уровне проекта и ведётся отдельным RFC. Приёмка 10.1B не меняет `docs/PRODUCT_SCOPE.md`, не подтверждает разрешённость внешнего протокола и не выполняет ротацию учётных записей.
