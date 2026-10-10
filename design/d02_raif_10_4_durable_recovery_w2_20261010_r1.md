# RAiF 10.4 / W2 — Durable Recovery, Side-Effect Safety, Windows Process Control

**Статус:** \`IMPLEMENTATION_PLAN / NOT_YET_TESTED\`. Дата 2026-10-10. Владелец: \`Rassvet_AI_Fabric\`; **точная кодовая база** \`main@8dc6ee32eabd3334012763bac8e641f682e478c6\` (tree \`8d2a0d0c195a3ffbb64cf26ba46e906936261894\`). Никаких изменений \`main\`, GitHub Tower, GDrive authority или активного Router только этим планом.

## 0. Приоритет и доказанный предшественник

F1 Windows isolated 10.3 closed as \`W1_OFFLINE_CORE_ACCEPTED_COMPOSITE\`: 428/428 unit (+20 worktree) из первого host run, затем 9/9 stages + \`mock\` + \`codex-mock\` + clean source из R2. Этот результат **не повторять механически**. При изменении исполняемого кода в W2 один полный регрессионный прогон обязателен; это не дубль старого независимого host run.

**Северная звезда W2:** восстановление задачи без слепого повторения внешнего эффекта, с точным журналом, идемпотентностью, зафиксированным правом и диагностируемым \`UNKNOWN_OUTCOME\`. Устойчивость SQLite не означает устойчивость удалённого эффекта.

## 1. [--] Отказные контрпримеры, которые должны первыми падать

1. Внешний action выполнился, процесс умер **до фиксации ACK**: \`recover\` не может знать, был ли эффект. Требуется \`UNKNOWN_OUTCOME / BLOCKED\` и сверка по durable operation_id; без независимого readback — никакого автоматического requeue.
2. Два конкурирующих worker / одна task/одна revision: недопустимы два \`COMMITTED\` одного logical intent. \`BEGIN IMMEDIATE\`, целевой CAS, fencing поколения и ledger receipt должны находиться в одной локальной транзакции; для внешнего target это всё равно лишь протокол, пока нет host-side equivalent.
3. Конфликт \`same operation_id + different intent_digest\`: отказ до эффекта. **Разные intents при одинаковом payload** не должны автоматически считаться дубликатами. Семантика dedup строго \`target_id+logical_operation_id+payload_digest\`.
4. Процесс умер или истёк timeout, а дочерний процесс ещё жив: нельзя считать kill исходного PID завершением всего дерева. Проверить только owned Windows Job Object / child subtree; никакой \`taskkill /F /IM language_server.exe\` или управления чужой IDE.
5. Отменена/истекла аренда, поздний worker завершает работу: прежний \`lease_epoch\` и хэш токена не должны подтвердить запись результата, новый owner не вправе принять старый ACK без target reconciliation.
6. Power loss после SQLite commit, до durable fsync: не приравнивать simulation к физическому тесту питания; при повреждении WAL, истечении locking timeout, странной ревизии — fail-closed + ручной recovery.

## 2. [==] Реализационная волна (один пакет, не N микрочекпойнтов)

**W2-A — состояние внешних эффектов:** новый изолированный SQLite \`effect_operations\` ledger с минимумом \`task_id, operation_id, target_id, payload_sha256, lease_epoch, expected_revision, phase, created_at, updated_at\`, плюс immutable \`effect_receipts\` (target revision, applied hash, readback class). Поля токенов, OAuth и raw промпты туда не писать. Состояния \`PREPARED, MAY_HAVE_RUN, APPLIED_VERIFIED, NO_EFFECT_VERIFIED, UNKNOWN_OUTCOME, BLOCKED_RECONCILE\`; не разрешать переход \`UNKNOWN_OUTCOME → PREPARED\` без внешнего подтверждения и нового controlled operation.
 
**W2-B — модуль и контракт Core:** использовать существующий \`FabricStore.atomic()\`, \`lease_epoch\`, checkpoint и \`recover()\`, не создавать второго владельца TaskGraph. Сформировать API \`prepare_effect(task, owner, lease, intent)\`, \`record_possible_dispatch(operation_id)\`, \`reconcile_effect(operation_id, evidence)\`, \`recover_pending_effects()\`. \`prepare_effect\` записывает намерение до запуска; фаза \`MAY_HAVE_RUN\` предшествует возможному external invocation. Любая потеря ACK — \`UNKNOWN_OUTCOME\`, а не автоматический PASS/retry. \`reconcile_effect\` требует pinned target + revision/receipt+source evidence, а не произвольное \`acknowledge\` длиной 12 символов.

**W2-C — процессный контур Windows:** ограниченный \`Windows Job Object\` только для дочерних процессов, созданных Fabric, закрытие дескрипторов и bounded cancel/timeout. Отдельный \`ProcessIdentity(pid, creation_time, owned_job)\`; совпадение PID не равно совпадению процесса/учётной записи. Отказ запускать новый child при отсутствии безопасной группировки; обязательный quiet shutdown + proof no owned descendants. Для synthetic/mock можно оставлять без Job Object с честным \`NO_EXTERNAL_CHILD\`.

**W2-D — schema/migration:** новый sqlite schema v2 только через проверяемое opt-in на **изолированной тестовой БД**, backup+readback; текущая пользовательская БД не мигрирует автоматически. Стабильность существующих CLI, JSON машинных полей и русского operator UX сохранить. Оба вида \`mock/codex-mock\` продолжают работать, новые поля только additive/explicit contract.

**W2-E — 1 тестовая матрица (в одном объединённом запуске):** exact local SQLite diskfile, 2 connections, 2 independent processes, stale fence, wrong/expired lease, payload collision, same intent replay, different intent same payload, crash before dispatch, crash after dispatch but before ACK, lost ACK, durable reopen, directory junction rejection, cancelled child subtree, simulated powerloss vs real-host \`NOT_TESTED\`. Минимум 3 уровня evidence: pure unit, owned-process integration, Windows host acceptance. Не вставлять tokens/raw paths в RESULT. Существующие unit regressions в одной CI, не 428 на каждый правочный коммит.

## 3. [++] Гейты W2

- **F2.0 Source:** isolated candidate branch от exact \`main\` tree, diff только allowlisted code/tests/docs, нет разрушения исходного \`C:\GIT\Rassvet_AI_Fabric\`.
- **F2.1 Unit:** все новые контракты и отрицательные fault тесты PASS, старые 428 regression не ломаются; skips/failures=0. Число тестов определяется живым discovery, не предположением.
- **F2.2 Windows host:** два реально независимых локальных процесса конкурируют за **один** изолированный file-backed sink; restart+lost ACK; нет двойного эффекта, нет orphan child; exact tests/version/sha.
- **F2.3 Evidence:** \`UNKNOWN_OUTCOME\` не превращается в \`PASS\` даже при восстановлении после сбоя; test harness сохраняет отдельный \`source_claim\` и \`readback_evidence\`.
- **F2.4 Gate:** отдельный независимый QA на **точный кандидатный SHA**, нет live account/remote provider/authority writes. Только после него предлагать PR и отдельный user MTD на merge конкретного SHA.

**Fail closed:** любое доказательство от внешнего source может быть неполным. SHA-256 checksum ≠ подпись, SQLite single-file CAS ≠ глобальный consensus, unit tests ≠ provider attestation, real login/identity/credential write по этому плану запрещены.

## 4. [~~] Маршрут и экономия

Одна отдельная кандидатная ветка \`raif-10-4-durable-recovery-w2-20261010\`, основанная на точном main 10.3 **после preflight**. Один крупный source+tests commit → одна Windows CI → один пользовательский RESULT ZIP, без ненужных повторов старых checkpoint и операций с подписками.

Если W2 частично не прошёл, не переименовывать статус в SUCCESS: оставить кандидатную ветку, исправить только контрпример и выполнить единый rerun в конце корректировки. Старый main и 134 WIP на \`C:\` сохраняются.

**W2 cursor:** \`W2/10_4_EFFECT_LEDGER_AND_OWNED_PROCESS_HARDENING\`. После F2 acceptance → \`W3/10_5_EXECUTOR_AND_MANUAL_ANTIGRAVITY_HANDOFF\`. **AG/G2 CLOSED, Tower BPR5 candidate unsealed.**
