# RAiF 10.6 — офлайн-контракт безопасного цикла разработки

**Статус:** synthetic-only candidate; Windows CI и независимая QA принимаются на точном SHA. **Не production autopilot, не live Codex/Antigravity и не автоматический merge.**

## Зачем

Реализовать один доказуемый этап: существующая задача SQLite `FabricStore` (`provider=mock`) → явный claim с lease → чистый pinned Git checkout → отдельный detached worktree из `worktree_review` → фиксированная безопасная правка `sandbox_demo/arithmetic.py` → три локальных синтетических теста → пакет доказательств → запрос независимой QA → структурированное намерение создать DRAFT PR. Код не отправляет git push, не использует GitHub-credential, не запускает LLM, не обращается к провайдеру и не вызывает merge.

**Автопилот** здесь означает автоматизацию допущенных *офлайн-шагов*; настоящая работа модели над произвольным кодом и независимый аудитор остаются **не реализованы** и требуют отдельных gates. Не заявлять end-to-end PR публикацию внутри модуля.

## Запуск и изоляция

- Python 3.11+, Windows. База SQLite заранее создаётся оператором **только явно** в изолированном каталоге. В ней создаётся задача `mock` с `workspace` равным разрешённому источнику Git. `run_synthetic_cycle(store, task_id, source, exact_head, output_root)` выполняет один подготовительный цикл; исходник C:\GIT\Rassvet_AI_Fabric жёстко запрещён для этого пути из-за сохранённых WIP.
- `output_root` расположен на локальном диске, вне источника и вне каталога БД (для среды владельца: `D:\ЗАГРУЗКИ`). Нельзя использовать UNC, mapped SMB, reparse points, грязный source clone или нечётный HEAD. Подготовка preflight выполняется **до** выдачи lease, включая Git HEAD и `git status`.
- Worktree регистрируется в Git `worktrees` источника и сохраняется для ревью, **не удаляется автоматически**. Копирование исходного checkout и fetch не выполняются. Произвольные пользовательские команды и тесты никогда не исполняются.
- Отказ после claim переводит исходную задачу в `BLOCKED` с фиксированным кодом, без автоматического повторного исполнения; неудача settlement при утраченной аренде требует ручной сверки существующим `store.recover()`.

## Артефакты в `RAIF_10_1_<id>`

Сохраняются прежние доказательства 10.1: `MANIFEST.json`, `STAGES.jsonl`, `REVIEW.patch`, `CHECKPOINT.json`, отсоединённое `workspace/`.

10.6 добавляет строго типизированные:

- `DEV_TASK.json`: task ID, recipe ID, exact base SHA, patch SHA-256, один разрешённый путь, digest цели (не сырой objective), 3 mock теста; модельных/провайдерных вызовов 0.
- `QA_REQUEST.json`: внешний независимый clean-context ревью обязателен; начальный статус `NOT_PERFORMED`.
- `DRAFT_PR_INTENT.json`: **только данные**. `branch_committed=false`, `remote_pr_created=false`, `publication_authorized=false`, `merge_authorized=false`.
- `CYCLE_RECEIPT.json`: SHA-256 всех трёх входных артефактов и точный cursor; readback с проверкой байтов. SHA-256 — контроль целостности, **не подпись доверенной роли**.

`verify_cycle_receipt(run_dir)` проверяет неизменность manifest, checkout, patch, receipt, разрешённого файла и QA/PR границ без выдачи полномочий. Поддельный внешний `PASS`-файл не меняет статус.

## Критерии допуска PR и merge

1. Подготовленный patch и 3/3 synthetic checks: `PACKAGE_READY_QA_PENDING`, а не `PROD_ACCEPTED`.
2. Независимая QA из отдельной доверенной роли сверяет exact base SHA, diff и эффект; CI сам по себе не является независимой QA. Повторное самостоятельное readback называется `AUTOMATED_CROSSCHECK`.
3. Уполномоченный GitHub-диспетчер отдельно готовит feature-commit и DRAFT PR на точном SHA. Этот модуль **не** имеет capability GitHub write.
4. MTD владельца на **точный PR/SHA** и актуальный review/CI gate требуется перед merge. `mtd` не выдаёт права менять CORE, Router, account policies или провайдеры вне его предмета.
5. Нельзя считать один synthetic add готовым универсальным автономным разработчиком. Следующий этап — отдельно допущенный real turn с доказательством разрешённости transport, отсутствия платного API fallback и отзыва полномочий.

## Negative QA cases

Wrong head, wrong source root, dirty checkout, disallowed provider, stale queue lease, dependency not ready, dirty/modified diff, metadata tampering, fake QA PASS, deleted intent, SHA drift, forbidden C: checkout, source/output overlap: **BLOCK** до записи PR. При успешной синтетике **нет** push, merge, source-commit и внешних API-вызовов.

**Текущий курсор:** `RAIF/10_6_INDEPENDENT_QA_AND_DRAFT_PR_GATE`. **Примечание:** GitHub-hosted CI не доказывает работу в физическом Windows-окружении владельца.
