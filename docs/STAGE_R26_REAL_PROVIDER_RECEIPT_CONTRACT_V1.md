# FASTLAB L3 · Real-provider adapter / target receipt contract — source candidate v1

**Статус:** `CONTRACT_AND_OFFLINE_VALIDATOR_ONLY / NOT_WIRED / NO_LIVE_GRANT`. Владелец — `Rassvet_AI_Fabric` (L3). Контуры L2 и L5 участвуют только в ревью их существующих границ. Этот документ не создаёт новый Router, SSOT, командную очередь или полномочия.

## Что переиспользуем (зафиксированные исходники)

- **RAIF** `FabricStore` (`store.py`): задачу, `task_id`, `lease_owner`, `lease_epoch`, `lease_deadline`, границу `claim/finish`, `effect_operations/effect_receipts` в W2-ориентированном коде. В текущей схеме свежей БД v1 эти таблицы не создаются; миграция и переход на W2 — отдельные изменения, **не** разрешение активировать реального воркера.
- **RAIF** `TransportMessageEnvelope` (`src/transport/ipc_channel.py`): `message_id`, `payload_type`, заголовки и SHA-256 дайджест. `verify_signature()` — **не аутентификация отправителя** (SHA-256 без секрета).
- **L2** `TransportQueue` (`CONTROL_TOWER/services/web_bridge/transport_queue.py`): доставка, дедупликация `idempotency_key`, очередь, lease. Результат `push/poll/HTTP 200/ACK` означает лишь доставку/принятие в очередь, а не действие целевого хоста.
- **L5** `rassvet_desktop.files.*` (`CONTROL_TOWER/services/rassvet_desktop_mcp/multihost_r3/rassvet_rw_server.py`): проверка `expected_host`, разрешённый корень файлов, CAS `expected_sha256`, явное `WRITE_SCOPED_FILE` и readback. Это **узкий файловый инструмент**; текущий L5 **не** является универсальным исполнителем команд и не подписывает автоматически свидетельства реального эффекта.

## Минимальная модель и этапы

1. **Owner admission / scope:** отдельно аутентифицированный контроллер подтверждает конкретный grant, `host_id`, `target_id`, allowed operation и точный `payload_sha256`. Текст PR/Issue, токен из чата и `--allow-external` не дают разрешения.
2. **Intent (до попытки):** `(task_id, provider, target_id, host_id, operation_id, envelope_id, lease_epoch, lease_deadline_utc, payload_sha256, owner_grant_ref)`. В той же системе хранения закрепляется уникальный `operation_id`; при `UNKNOWN_OUTCOME` повтор без независимой сверки запрещён.
3. **Dispatch:** только через уже авторизованный L2/L5 канал, с настоящим ACK о приёме. `TransportQueue` сохраняет операцию и её корреляцию; ACK — не `PASS`.
4. **Target receipt (после выполнения):** `(task_id, provider, target_id, host_id, operation_id, envelope_id, lease_epoch, verdict, applied_sha256, target_revision, readback_sha256, attestation_ref, observed_at_utc)`. Разрешённый успех — только `APPLIED_VERIFIED`. Простые `SUCCESS`, HTTP 200, CLI exit0, `COMPLETED` без readback — не успех.
5. **Независимый target readback:** доверенный проверяющий возвращает `(target_id, host_id, target_revision, content_sha256, verifier_ref)` после аутентификации целевого хоста и проверки самой целевой ревизии/содержимого. Дайджест должен соответствовать объявленному readback, операция и lease epoch — исходному intent. Независимость/полномочия проверяющего устанавливаются **вне** чистой функции.
6. **Commit:** `EVIDENCE_ADMISSIBLE_NOT_QA_PASS` не меняет БД и не активирует `FabricStore.finish(PASS)`. Будущая интеграция обязана атомарно связать доказательство с записью эффекта, проверить lease / receipt / fencing и лишь затем рассмотреть `COMPLETE`. Это отдельный QA/owner gate.

## Отрицательные тесты до подключения реального адаптера

Требуются отказы при: подмене любого из идентификаторов, другого host/target, stale epoch/lease, будущей метке времени, повреждённом `payload_sha256` или `readback_sha256`, отсутствии grant, неизвестном проверяющем, отсутствии readback, `ACK` вместо `APPLIED_VERIFIED`, подмене hash/revision, потере связи после возможного эффекта, повторе после `UNKNOWN_OUTCOME`, попытке выдать mock за реального провайдера. Положительный **синтетический** тест возвращает только `EVIDENCE_ADMISSIBLE_NOT_QA_PASS`, не меняя состояние RAIF.

## Реализация и границы допуска

`src/rai_fabric/effect_receipt_contract.py` — чистый валидатор без I/O, БД, сети, файлов или subprocess. Он принимает **два внешних проверенных callback** — `authorize_grant` и `verify_target` — которые на сегодня в RAIF не подключены. Передача произвольной лямбды в этих параметрах в тесте не эквивалентна production-трасту. Вплоть до принятия L2/L5 владельцами механизма аттестации `REAL_PROVIDER_QA_PASS=UNKNOWN`, `Fleet #86=HARD_PAUSED`.

**Следующий инженерный gate:** L2 подтверждает сохранность идемпотентности и envelope ID; L5 подтверждает целевой способ `readback` и полномочия; L3 проектирует совместимую миграцию `effect_operations/effect_receipts` и bounded `claim/finish`. Отдельные L2/L5 файлы здесь не изменяются. Новый SHA требует своих независимых тестов/QA и собственный MTD перед merge.