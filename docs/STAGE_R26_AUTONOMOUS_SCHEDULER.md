# RAiF 10.8: Автономный диспетчер очередей воркеров (Stage R26 — Autonomous Worker Fleet Scheduler)

**Идентификатор этапа:** `RAIF_10_8_STAGE_R26`  
**Канонический чекпойнт:** `CHECKPOINT_2026-10-14_STEP3_RAIF_10_8_SCHEDULER`  
**Связанные Issue:** [Rassvet_AI_Fabric#17](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/17), [#20](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/20)  
**Актуальный статус main (проверка 23.10.2026):** `DEPLOYED_MAIN / WAVE1_4_VERIFIED / 34_OF_34_WINDOWS_QA_PASS / REAL_PROVIDER_CANARY_PENDING_ADMISSION`  
**Исторический статус от 21.10.2026:** `SOURCE_RISK_VERIFIED / MOCK_ONLY_TEST_COVERAGE / NOT_PRODUCTION_READY` (исходный дефект nonmock PASS устранён в коммите 56f7154).  
**Исторический статус от 14.10.2026:** `IMPLEMENTED / VALIDATED / PRODUCTION_READY` — сохранён как утверждение исходного этапа.  
**Обязательная корректирующая запись:** [RAIF #21](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/21).  

**Классификатор:** `[Класс A - X]`

---

## 0. Граница доказательств и допуск к выпуску (21.10.2026)

Проверены исходники `Rassvet_AI_Fabric/main@32be4df878b13d3c36242a2d0eb81f2406eafc84`. В `src/rai_fabric/scheduler.py` (Git blob `d534e95316e7f65562483de53cefe1b0da5d6860`) немоковый путь всё ещё содержит `FabricStore.claim()` и немедленный `finish(verdict="PASS")` **без подтверждённого запуска реального провайдера или сверенного target receipt**. Это **риск, воспроизводимый анализом исходников**, не доказательство фактического инцидента на хосте. `FabricStore` main (blob `d4472dae5d341a9e1053a8247c16f7f1915f3f63`) остаётся вне исправленной ветки. Действующий `main` **не имеет права называться `PRODUCTION_READY` для реальных исполнителей**.

**Границы исторических проверок:** `tests/test_scheduler.py` охватывает mock-сценарии; исторические результаты раздела 3 и заявленная архитектура раздела 1 не удостоверяют реальное исполнение `antigravity`/`codex-app`, Windows/host exact HEAD, GPU, независимый QA или production deployment. Успешный mock transport не равен `PRODUCTION_QA_PASS`.

**Изолированный кандидат, НЕ установленный в main:** `labqa/l3-wave4-windows-telemetry-deny-invalid-20261020-r1@3e2bf8ce9399c4b2a59f06416e6d219376dc68c3`. Wave1–Wave4 закрывают отрицательные source-кейсы nonmock false PASS, готовность mock-очереди и безопасную маршрутизацию telemetry на уровне отдельных тестов. На точном Wave4 было **23 PASS / 0 FAIL**, Linux/Python 3.13.5, с симуляцией Windows веток и заглушками внешнего I/O; это `SELF_TEST_ONLY`, **не** независимый Windows QA. По отношению к актуальному main ветка расходится: 4 коммита впереди / 1 позади. Нельзя смешивать доказательства разных SHA или объявлять Wave4 установленным.

**Выпуск заблокирован до отдельной проверки:** owner review и отсутствие пересечений изменений → проверенный exact интеграционный SHA → native Windows offline QA в изолированном worktree и фактический exit/JUnit/dirty/ignored → независимый QA-ACCEPT → только затем scoped canary, deployed readback и rollback. Никакие пункты этого перечня не считаются пройденными из факта публикации branch/ZIP/issue. `UNKNOWN != PASS`. Fleet [CONTROL_TOWER #86](https://github.com/rassvetpublic-spec/CONTROL_TOWER/issues/86) остаётся `HARD_PAUSED`; [#113](https://github.com/rassvetpublic-spec/CONTROL_TOWER/issues/113) — `DATA_ONLY`.

Разделы 1–3 ниже сохраняют **историческое техническое описание и заявленные проверки Stage R26**; они не заменяют актуальный release gate. Этот документ не изменяет active authority, правила хоста, маршрутизатор, main или действующий runtime.

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

---

## 4. Пострелизный аддендум: фиксация выпуска 56f7154 (23.10.2026)

**Статус выпуска:** `DEPLOYED_MAIN / FASTLAB_L3_VERIFIED_STAGE_R26`  
**Выпущенный SHA:** `56f7154ee22640063d17bae402ecaeb8c5c29124` (fast-forward merge в `main` под мандатом владельца MTD 011011, опубликован на `origin/main`).  
**Связанный чекпойнт:** `FASTLAB_L3_INTEGRATED_CANDIDATE_20261023_R1`  
**Google Drive L3 квитанция:** [`FASTLAB_L3_INTEGRATED_CANDIDATE_20261023_R1.zip`](https://drive.google.com/file/d/1I2637t7czL4t90cltJPICY_Gj07XmPVy/view?usp=drivesdk) (SHA-256: `28A04738B4B0E26C6304C7ECE303C6D0FF3D781DB93B471C774B9806ABFA3C7A`).

### 4.1. Разрешённые дефекты и актуальные контракты (Downstream Contract Review)

1. **Запрет синтетического PASS для реальных провайдеров (`FabricStore.finish`):**
   - Устранён критический дефект ложного немедленного завершения немоковых задач без реального исполнения.
   - Метод `FabricStore.finish()` при вызове с `verdict="PASS"` для задач с `provider not in ('mock', 'codex-mock')` гарантированно выбрасывает `FabricError`.
   - В `FabricStore.submit()` запрещено создание немоковых задач, зависящих от моковых заглушек.

2. **Справедливость диспетчеризации мок-очереди (`WorkerFleetScheduler._claim_pending_tasks`):**
   - Устранено голодание задач: зависшая, заблокированная зависимостями или не имеющая зарегистрированного воркера задача больше не блокирует последующие готовые мок-задачи в FIFO-очереди.

3. **Безопасный контракт именованного канала телеметрии Windows (`\\.\pipe\fleet_metrics`):**
   - В `_emit_telemetry()` на платформе Windows (`os.name == 'nt'`) строго валидируется префикс `\\.\pipe\` и непустое имя канала.
   - Некорректные или удалённые адреса пайпов отклоняются fail-closed (`return`) без несанкционированного fallback в сетевой сокет TCP (`AF_INET`).
   - Обеспечена полная совместимость с сервером метрик `CONTROL_TOWER/services/metrics_intake/pipe_server.py`.

### 4.2. Результаты нативного Windows QA
- Проверено на хосте `RASSVET_DESKTOP` (Windows 11 / PowerShell 7.6.7 / Python 3.13.14 / pytest 9.1.1):
  - Пакет Wave1–Wave4: **23/23 PASS** (с `qa_no_io_guard.py`);
  - Регрессия Horizon `main`: **5/5 PASS**;
  - Пропускная способность и консенсус планировщика: **6/6 PASS**;
  - Итог: **34/34 PASS, exit code 0**.

### 4.3. Статус канареечного тестирования (Canary Status)
- **SEPARATELY_ADMITTED_CANARY:** Запуск боевых сервисов флота, подключение внешних сетевых провайдеров (Claude/Gemini API) и снятие паузы с супервизора (`CONTROL_TOWER #86 HARD_PAUSED`) требуют **отдельного явного допуска владельца**.
- В отсутствие отдельного допуска планировщик находится в проверенном офлайн-состоянии; фоновые демоны не запускаются.
