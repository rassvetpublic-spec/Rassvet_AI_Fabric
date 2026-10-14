# RAiF 10.8: Автономный диспетчер очередей воркеров (Stage R26 — Autonomous Worker Fleet Scheduler)

**Идентификатор этапа:** `RAIF_10_8_STAGE_R26`  
**Канонический чекпойнт:** `CHECKPOINT_2026-10-14_STEP3_RAIF_10_8_SCHEDULER`  
**Связанные Issue:** [Rassvet_AI_Fabric#17](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/17), [#20](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/20)  
**Статус:** `IMPLEMENTED / VALIDATED / PRODUCTION_READY`  
**Классификатор:** `[Класс A - X]`

---

## 1. Архитектурная цель и назначение

Диспетчер очередей задач флота (`WorkerFleetScheduler`) обеспечивает непрерывную оркестрацию распределённых исполнителей Rassvet AI Fabric, автоматическое распределение задач из `FabricStore`, пулинг воркеров, ротацию Google-аккаунтов супервизора и каскадное переключение на модели Claude (CP-55).

### Ключевые возможности планировщика:

1. **Автономная очередь FabricStore (QUEUED -> RUNNING -> COMPLETE):**
   - Неблокирующее сканирование очереди задач;
   - Защита от дублирования исполнения и гонок за задачи между конкурентными процессами;
   - Автоматическое продление аренды (lease) и fail-closed восстановление зависших задач (`store.recover()`).

2. **Пулинг и жизненный цикл воркеров (Worker Fleet Pooling):**
   - Динамическая регистрация и дерегистрация воркеров (`register_worker`, `unregister_worker`);
   - Статусы воркеров: `IDLE`, `BUSY`, `DRAINING`, `OFFLINE`;
   - Отслеживание статистики: выполненные задачи, сбои, время исполнения (`execution_ms`), heartbeat.

3. **Интеграция с пулом супервизора и балансировка квот:**
   - Round-robin ротация учетных записей из пула `account_pool`;
   - При исчерпании квот основного аккаунта супервизор переключает сессию;
   - При исчерпании всех квот Gemini активируется каскадный роутер `FailoverRouter` (Claude Haiku / Sonnet).

4. **Интеграция с боевым IPC-транспортом (Stage R25):**
   - Возможность передачи конвертов `TransportMessageEnvelope` по `\\.\pipe\raif_transport` или HTTP fallback `18892`;
   - Стриминг телеметрии в `\\.\pipe\fleet_metrics` с гарантией Zero SSD Wear.

---

## 2. Модули и Sidecar-паспорта

Компоненты паспортизированы по стандарту `BPR40_SIDECAR_PASSPORT/1.1`:

| Файл | Назначение | Паспорт |
|---|---|---|
| `src/rai_fabric/scheduler.py` | Реализация `WorkerFleetScheduler`, `WorkerInfo`, `SchedulerConfig` | `scheduler.passport.json` |
| `src/rai_fabric/failover_router.py` | Каскадный роутер моделей (Gemini -> Claude Haiku -> Claude Sonnet) | `failover_router.passport.json` |
| `src/rai_fabric/claude_vertex_transport.py` | Адаптер Claude Vertex AI ADC (CP-55) | `claude_vertex_transport.passport.json` |
| `src/transport/real_transport.py` | Боевой IPC-транспорт и мост метрик | `real_transport.passport.json` |

---

## 3. Результаты тестов и верификация

- **Тесты планировщика:** `tests/test_scheduler.py` — **PASS** (детерминированный FIFO-порядок, пулинг, ротация аккаунтов, восстановление аренды);
- **Тесты Claude Failover:** `tests/test_claude_failover.py` — **10/10 PASS** (офлайн-переключение при 429/503 и авто-возврат);
- **Сквозные E2E тесты:** `tests/test_e2e_fabric_supervisor_transport.py` — **PASS** (конвейер FabricStore -> Supervisor -> RealTransport).
