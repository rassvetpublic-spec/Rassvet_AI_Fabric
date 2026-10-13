# RAiF 10.7: Боевой межпроцессный транспорт (Stage R25 — Real Transport)

**Идентификатор этапа:** `RAIF_10_7_STAGE_R25`  
**Канонический чекпойнт:** `CHECKPOINT_2026-10-13_STEP2_RAIF_10_7_REAL_TRANSPORT`  
**Связанный Issue:** [Rassvet_AI_Fabric#15](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/15)  
**Статус:** `IMPLEMENTED / VALIDATED / PR_READY`  
**Классификатор:** `[Класс B - X]`

---

## 1. Архитектурная цель и назначение

Переход от синтетических оффлайн-заглушек к боевому межпроцессному транспорту (IPC Layer) для интеграции исполнителей Rassvet AI Fabric с ядром `CONTROL_TOWER`, `KAT9I_OS` и `Antigravity Supervisor`.

### Ключевые компоненты архитектуры:

1. **Первичный канал Windows (Primary Named Pipe):**
   - Канал: `\\.\pipe\raif_transport` (`NamedPipeServer` и `NamedPipeClient`);
   - Сериализация: детерминированный канонический JSON / JSON-RPC конверт (`TransportMessageEnvelope`);
   - Защита: криптографическая SHA-256 подпись каждого конверта с проверкой на приеме (fail-closed);
   - Авто-переподключение: неблокирующее восстановление связи при перезапуске сервера или обрыве канала.

2. **Резервный сетевой шлюз (Fallback Layer):**
   - Адрес: `http://127.0.0.1:18892` (`HttpFallbackServer` и `HttpFallbackClient`);
   - Эндпоинты:
     - `GET /health`, `GET /status` — проверка жизнеспособности и метрики очереди;
     - `POST /rpc`, `POST /messages` — приём подписанных конвертов сообщений;
     - `GET /poll` — опрос очереди сообщений клиентами.

3. **Потоковый мост метрик и телеметрии (Fleet Metrics Bridge):**
   - Канал: `\\.\pipe\fleet_metrics` (`FleetMetricsBridge`);
   - Гарантия Zero SSD Wear: при недоступности пайпа метрики буферизуются в кольцевом буфере ОЗУ (до 5 000 записей);
   - Автоматическая передача heartbeats, событий маршрутизации и статистики доставки.

4. **Интеграция с Antigravity Supervisor ([RAiF#13](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/13)):**
   - Модуль `RealTransportAdapter` транслирует статусы супервизора (`register_supervisor_status`);
   - Маршрутизация запросов к моделям (`route_model_request`) с привязкой к Google-аккаунтам.

---

## 2. Модули и Sidecar-паспорта

Все модули паспортизированы по стандарту `BPR40_SIDECAR_PASSPORT/1.1`:

| Файл | Назначение | Паспорт |
|---|---|---|
| `src/transport/__init__.py` | Корневой экспорт пакета транспорта | `__init__.passport.json` |
| `src/transport/ipc_channel.py` | Интерфейсы `ITransportChannel`, конверт `TransportMessageEnvelope` | `ipc_channel.passport.json` |
| `src/transport/real_transport.py` | Серверы, клиенты Named Pipe, HTTP Fallback, MetricsBridge, RealTransportAdapter | `real_transport.passport.json` |
| `src/rai_fabric/transport.py` | Мост обратной совместимости для пространства `rai_fabric` | `transport.passport.json` |

---

## 3. Результаты верификации (564/564 PASS)

- **Unit- и интеграционные тесты:** `tests/test_transport_real.py` — **10/10 PASS** (0 failures, 0 errors);
- **Полная регрессия набора тестов:** `scripts/run-tests.ps1` — **564/564 PASS** (0 failures, 0 errors);
- **Аудит Sidecar-паспортов:** `scripts/sidecar_passport_validator.py src` — **53/53 PASS** (0 нарушений).
