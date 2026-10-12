# RAiF W2 / 10.4–10.5 — Durable Effect Ledger и Windows Owned Job

**Статус:** изолированный кандидат **W2-A/B/C (synthetic-only)**. Без эксплуатационного допуска. Основа — `main@34e5f83652b65a4924fb48ff5aeeb90dde2783a7`, PR #5 объединён, Windows CI main #38185243827 = 481/481 PASS.

## Обязательные ограничения

- Ни одно состояние SQLite само по себе **не** доказывает выполнение либо отсутствие действия во внешнем провайдере. Успех синтетического приёмника **не является** разрешением запускать реальный Antigravity, Codex или другие provider-интеграции.
- Новый ledger создаётся **только явным** `EffectLedger.install_on_empty_store(FabricStore(..., initialize=True))` на пустой изолированной базе. `schema_version=2` и таблицы `effect_operations`, `effect_receipts` не мигрируют действующую пользовательскую БД автоматически. Старые `mock` и `codex-mock` в schema v1 остаются без изменения контрактов.
- В schema v2 внешний `run_one(..., provider="antigravity")` и другие реальные провайдеры блокируются **до claim**, поскольку нет verified target-adapter. Это явное закрытие gate, не скрытая деградация.
- `C:\GIT\Rassvet_AI_Fabric` (последний отчёт 134 tracked WIP) не затрагивать; Tower/CKS/Router/BPR40 authority, реальную идентичность аккаунтов, .codex, настройки подписок и реальные provider calls не использовать.

## W2-A/B: фазы и порядок

1. `PREPARED`: под действующим `lease_owner + lease_token + lease_epoch` записать неприватные `task_id, target_id, operation_id, payload_sha256, expected_revision`. Без сырого payload/token.
2. `MAY_HAVE_RUN`: **однократный** `mark_possible_dispatch` фиксируется в `BEGIN IMMEDIATE` и коммитится до любого возможного вызова target. Второй вызов с тем же intent либо новым worker блокируется.
3. Если lease истёк до ACK, `FabricStore.recover()` выполняет в **одной локальной транзакции** перевод `MAY_HAVE_RUN → UNKNOWN_OUTCOME` и `RUNNING → BLOCKED`. Попытки `requeue` задачи с любым ledger-записанным эффектом запрещены даже при длинном текстовом acknowledgement. `PASS` запрещён при не-APPLIED_VERIFIED эффектах.
4. `reconcile_synthetic` использует **другой SQLite-файл** как test target. Совпадение `target_id/operation_id/payload_sha256/expected_revision` и readback ревизии `1` подтверждает только `APPLIED_VERIFIED` в синтетике. Пустой readback после `MAY_HAVE_RUN` **не означает** no-effect: `BLOCKED_RECONCILE`.
5. Отсутствие target-записи при фазе `PREPARED` (вызов гарантированно не разрешён) допускает `NO_EFFECT_VERIFIED` только для synthetic; `PASS` задачи всё равно запрещён. Каждая локальная синтетическая сверка сохраняет immutable receipt с SHA-256 метаданных. Контрольная сумма — не подпись независимого target.
6. Двойное применение logical operation с другим digest запрещено, как и повторное выполнение via `requeue`. Отдельный target effect может подтверждаться только тестовым адаптером; новые controlled intents требуют отдельной задачи и идентификатора.

Таблицы schema v2 находятся внутри исходного `FabricStore` и используют его `atomic()`, fencing аренды и события. Нет второго глобального TaskGraph и записи в CKS/Башни.

## W2-C: Windows-процессы

- `windows_owned_job.py` запускает **только четыре встроенных synthetic-кейса** `EXIT_ZERO`, `EXIT_NONZERO`, `HANG_PARENT`, `SPAWN_DESCENDANT`. Код произвольного исполнителя или пути к сторонним приложениям принимать **не может**.
- На Windows `CreateProcessW(CREATE_SUSPENDED)` → собственный `CreateJobObjectW` с `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` → `AssignProcessToJobObject` → `ResumeThread`. Если назначение не удалось, процесс уничтожается ещё в suspended-состоянии, без unsafe gap.
- По тайм-ауту `TerminateJobObject` применяется **только** к нашему Job handle, не к PID по имени и не к IDE пользователя. `QueryInformationJobObject(ActiveProcesses)` подтверждает отсутствие собственных детей. Отказ или неизвестное состояние — fail-closed; Windows чужие процессы не трогать.
- Это **не** готовый runtime supervisor и не гарантия против кражи child-handle, внешних эффектов, powerloss либо race в чужих процессах.

## Приёмка и матрица

- `tests/test_w2_effect_ledger.py`: opt-in schema, несовместимый schema1 migration, неверный/просроченный lease, два независимых SQLite соединения, конфликт ID/digest, разные intents при одинаковом payload, однократный dispatch, crash/lost ACK после применения в **другом процессе**, reopen, иммутабельность receipts, запрет requeue, синтетический readback, отсутствующий proof и конфликт ревизий.
- `tests/test_w2_windows_owned_job.py`: Windows Job Object, exit code, timeout/kill parent и descendants, fail-closed неизвестного кейса/пути. На Windows тесты **обязаны выполняться**, на других ОС помечены как Windows-only.
- Существующий Windows runner: `scripts/run-tests.ps1` → `python -m unittest discover -s tests -v`, после него отдельные `demo.ps1` и `demo-codex-mock.ps1`; никаких новых платных/облачных fallback.
- Один точный Windows CI только на source PR. Отдельная независимая QA точного SHA обязана искать реальный double-dispatch, lost-ACK, unsafe shortcut и неподтверждённое убийство потомков. После source QA для W2-F2.2 потребуются отдельные доказательства на Windows владельца.

## Не реализовано этой волной

- Реальный внешний target readback adapter, подтверждение уникальности удалённого `operation_id`, target-owned idempotency receipt, physical powerloss/NTFS durability, автоматическое исправление повреждённого WAL, production Windows worker cancellation, провайдерный authorization gate.
- `W2_RELEASE / PROD_ACCEPTED` **не заявляется** даже при зелёной GitHub CI. Для PR требуется независимый QA и отдельное `OWNER MERGE MTD` на точный HEAD.

**Следующий курсор:** `RAIF/W2_F2_1_WINDOWS_CI_AND_INDEPENDENT_SOURCE_QA` → `W2_F2_2_OWNER_HOST_SYNTHETIC_LOST_ACK_AND_JOB_CHILDREN`.


## W2 R2 — adversarial safety hardening, after QA request

Проверка после CI514 выявила два обхода на низкоуровневом API:

1. W2 schema_version=2: запрет direct FabricStore.claim() для real provider,
   включая выбор без фильтра; PREPARED и MAY_HAVE_RUN не создаются для
   внешних задач даже при вручную испорченной строке аренды.
2. FabricStore.finish(PASS) требует не одну фазу APPLIED_VERIFIED, а
   существующий matching effect_receipts: verdict, payload digest и
   каноническую SHA-256 контрольную сумму. Пустой или повреждённый receipt
   запрещает COMPLETE. При этом SHA-256 не является подписью remote target.

Новые отрицательные тесты используют только отдельную временную SQLite
базу для fault injection. На Windows дополнительный тест имитирует отказ
AssignProcessToJobObject и доказывает, что ResumeThread не вызывается,
а suspended synthetic-child прекращается собственным HANDLE.

Кандидат также синхронизирован с новым main Level-4 PR #9 (защита каталога
Windows, host preflight). Эти изменения лишь наследуются; не означают
приёмку реальных worker/side-effects или отсутствие всех TOCTOU.

Любой новый SHA требует одну новую Windows CI и отдельную независимую QA.
Реальный аккаунт/провайдер не используется; owner merge MTD закрыт.
