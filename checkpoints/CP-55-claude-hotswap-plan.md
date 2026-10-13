# CP-55 — Горячее переключение на модели Claude (Claude Hot-Switch Plan)

**Дата:** 2026-10-13  
**Статус:** DRAFT / PENDING_GATE  
**Автор:** BPR5-NEXTGEN (Antigravity)  
**Ветка:** `claude-hotswap`

---

## 🎯 Цель

Научить RAiF-флот и оператора переключаться на модели Claude (Anthropic) «налёту»:
- для **простых задач** (экономия квоты Gemini / выгрузка рутины);
- как **аварийный исполнитель** при HTTP 429 / недоступности основной модели.

Режим работы: **тот же Google-аккаунт**, без отдельного биллинга Anthropic напрямую — через Vertex AI или через Antigravity Model Selection.

---

## 📋 Анализ вариантов доступа к Claude

### Вариант A — Antigravity Model Selection (САМЫЙ БЫСТРЫЙ, уже работает)

**Что есть сейчас:** Antigravity IDE уже поддерживает переключение модели через настройку  
`Model Selection` в правом верхнем углу чата (подтверждено — пользователь уже переключился на Claude Sonnet 4.6 в этом сеансе).

**Как работает:** Google предоставляет Claude через Antigravity как лицензированный партнёрский контент.  
Тот же Google-аккаунт — биллинг через Google, не через Anthropic Console.

**Доступные модели (Antigravity):**
- `Claude Haiku 3.5` — быстрый, дешёвый, простые задачи
- `Claude Sonnet 4.5 / 4.6` — баланс качество/скорость
- `Claude Sonnet 4.6 (Thinking)` — глубокое рассуждение

**Ограничение:** ручное переключение в UI; программного API для смены модели внутри чата нет.

---

### Вариант B — Claude через Vertex AI (Google Cloud)

**Официальная документация:** `https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/use-claude`  
**Новый canonical URL:** `https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude`

**Доступные модели через Vertex AI (на дату составления):**
- `claude-opus-4-5`
- `claude-sonnet-4-5`
- `claude-haiku-3-5`
- Новые — `claude-sonnet-4-6`, `claude-opus-4` (по доступности региона)

**Аутентификация:** Через Google Cloud ADC (Application Default Credentials) — тот же Google-аккаунт!  
Нет необходимости в ключе API Anthropic. Биллинг через GCP-проект.

**SDK Python:**
```python
import anthropic

client = anthropic.AnthropicVertex(
    region="us-east5",           # или europe-west1
    project_id="your-gcp-project"
)

message = client.messages.create(
    model="claude-sonnet-4-5",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Привет!"}]
)
```

**Зависимость:** `pip install anthropic[vertex]`

---

### Вариант C — Прямой Anthropic API

**URL:** `https://api.anthropic.com/v1/`  
**Аутентификация:** Отдельный API-ключ (`ANTHROPIC_API_KEY`) — ДРУГОЙ аккаунт/биллинг.  
**Статус для RAiF:** Резервный вариант; требует отдельного Anthropic Console.

---

## 🏗️ План реализации (Phased)

### Phase 0 — Документация и знание (уже выполнено в CP-55)
- [x] Анализ вариантов доступа
- [x] Подтверждение Antigravity Model Selection работает (пользователь переключился)
- [x] Документация в `checkpoints/CP-55`

### Phase 1 — Antigravity Model Selection SOP (Standard Operating Procedure)
**Файл:** `docs/SOP_CLAUDE_HOTSWAP.md`  
**Содержание:**
- Карта моделей (Gemini Flash → Claude Haiku, Gemini Pro → Claude Sonnet)
- Триггеры переключения: 429, degraded response, явный запрос оператора
- Шаблон промпта для Claude (системный контекст BPR5)
- Инвариант возврата: после устранения 429 — возврат на основную модель

### Phase 2 — Claude Vertex AI Transport (`claude_vertex_transport.py`)
**Путь:** `src/rai_fabric/claude_vertex_transport.py`  
**Контракт:** реализует `ITransportChannel` из `transport.ipc_channel`  
**Функциональность:**
- Инициализация через `google-auth` ADC (без отдельного ключа)
- Метод `send(message)` → Claude via Vertex AI
- Автоматический fallback: `429 / 503` → поднимает `TransportError(RATE_LIMITED)`
- Healthcheck: `probe()` → модель-эхо с тайм-аутом 3 сек

**Паспорт:** `claude_vertex_transport.passport.json` (BPR40_SIDECAR_PASSPORT/1.1)

### Phase 3 — RAiF Failover Router
**Путь:** `src/rai_fabric/failover_router.py`  
**Логика:**
```
Primary (Gemini/AGY) → на 429/503 → Claude Haiku (быстрый) → Claude Sonnet (сложный)
```
- Настраиваемый `retry_budget` (по умолчанию: 2 попытки на основной, потом fallback)
- Метрики: `model_switches_total`, `fallback_active`, `fallback_duration_seconds`
- Доставка метрик через `\\.\pipe\fleet_metrics` (CKS#457)
- `failover_router.passport.json`

### Phase 4 — Интеграционные тесты
**Путь:** `tests/test_claude_failover.py`  
**Сценарии:**
- `test_happy_path_gemini`: основной путь через Gemini — без переключений
- `test_429_triggers_claude_haiku`: мок 429 → активируется Haiku
- `test_503_triggers_claude_sonnet`: тяжёлый сбой → Sonnet
- `test_return_to_primary`: после восстановления → возврат на Gemini
- Синтетические mock-клиенты, без реальных API-вызовов (offline-safe)

### Phase 5 — Паспортизация и метрики
- Обновление `PROJECT_PASSPORT.yaml`: добавить раздел `claude_hotswap`
- Регистрация новых SLO: `failover_latency_p99 < 5s`, `fallback_success_rate > 99%`
- Обновление `BUILD_CHECKPOINT.json`

---

## ⚠️ Ограничения и инварианты

| Ограничение | Инвариант |
|---|---|
| Не хранить ANTHROPIC_API_KEY в открытом виде | `SECRETS_GATE: PASS` |
| Vertex AI требует включённого GCP-проекта с Vertex AI API | `[REQUIRED_USER_ACTION]` до Phase 2 |
| Смена модели не меняет контекст (нет истории между моделями) | Каждый failover — новый контекст |
| Не выполнять merge в main без `mtd` | Gate Владельца активен |

---

## 📊 Целевые метрики (SLO)

| Метрика | Цель (SLO) | Факт (базовый) |
|---|---|---|
| `failover_latency_p99` | < 5 сек | UNKNOWN (не измерено) |
| `fallback_success_rate` | > 99% | UNKNOWN |
| `primary_recovery_time` | < 60 сек после исчезновения 429 | UNKNOWN |
| `model_switch_manual_time` | < 10 сек (SOP) | ~5 сек (проверено вручную) |

---

## 🔗 Ссылки

- Antigravity Model Selection: Настройки чата → правый верхний угол → «Model Selection»
- Vertex AI Claude docs: https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/claude
- Anthropic Python SDK (Vertex): `pip install anthropic[vertex]`
- RAiF Transport contract: [`src/rai_fabric/transport.py`](../src/rai_fabric/transport.py)
- IPC Channel: [`src/transport/ipc_channel.py`](../src/transport/ipc_channel.py)
