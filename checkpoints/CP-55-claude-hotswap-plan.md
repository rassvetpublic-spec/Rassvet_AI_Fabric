# CP-55 — Горячее переключение на модели Claude (Claude Hot-Switch Plan)

**Дата:** 2026-10-14  
**Статус:** VERIFIED / PRODUCTION_READY  
**Автор:** BPR5-NEXTGEN (Antigravity)  
**Ветка:** `main`

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

### Phase 0 — Документация и знание (выполнено)
- [x] Анализ вариантов доступа
- [x] Подтверждение Antigravity Model Selection работает (пользователь переключился)
- [x] Документация в `checkpoints/CP-55`

### Phase 1 — Antigravity Model Selection SOP (выполнено)
- [x] Регламент `docs/SOP_CLAUDE_HOTSWAP.md`
- [x] Карта моделей (Gemini Flash → Claude Haiku, Gemini Pro → Claude Sonnet, Gemini Thinking → Claude Sonnet Thinking)
- [x] Триггеры переключения: 429, degraded response, явный запрос оператора
- [x] Инвариант возврата: `RETURN_TO_PRIMARY_ON_RECOVERY`

### Phase 2 — Claude Vertex AI Transport (выполнено)
- [x] Модуль `src/rai_fabric/claude_vertex_transport.py`
- [x] Контракт `ITransportChannel` из `transport.ipc_channel`
- [x] BPR40 sidecar паспорт `claude_vertex_transport.passport.json`
- [x] Обработка лимитов 429/503 и криптографическая валидация пакетов

### Phase 3 — RAiF Failover Router (выполнено)
- [x] Каскадный роутер `src/rai_fabric/failover_router.py`
- [x] Цепочка маршрутизации: Primary (Gemini) → Fallback (Claude Haiku) → Escalation (Claude Sonnet)
- [x] Паспорт `failover_router.passport.json`
- [x] Учёт метрик Zero SSD Wear в оперативной памяти

### Phase 4 — Интеграционные тесты (выполнено)
- [x] Люкс тестов `tests/test_claude_failover.py` (10/10 PASS)
- [x] 100% offline-safe mock-клиенты без сетевых вызовов

### Phase 5 — Паспортизация и каталоги (выполнено)
- [x] Регистрация в `src/CATALOG.md`
- [x] 15/15 PASS в `tests/test_sidecar_passports.py`

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
