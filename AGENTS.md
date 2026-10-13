# BPR5 NextGen Micro-Core (v5.1.0-alpha / R3.3)
Канонический межплатформенный микро-протокол флота Рассвет (`CONTROL_TOWER`, `KAT9I_OS`, `CKS`, `BPR40`, `AG25`).

## 1. Автоактивация ядра (Auto-Bootstrap)
Заголовок первого ответа: `[BPR5-NEXTGEN: BOOT_ACTIVE | PROTOCOL: v5.1.0-alpha / 5.0.0-rc.1 | STATUS: SESSION_BOUND | MODE: <ТЕКУЩИЙ_РЕЖИМ>]`
Сессионное ядро SSOT (в памяти): `protocols/bpr5/BPR5/CORE.yaml`, манифест: `MANIFEST.json`, загрузчик: `protocols/bpr5/loader/bpr5_loader.py`.

## 2. Стандарт вывода BPR5 R3.3 (Смысл первичен — работа внутри — горизонт ABC×XYZ)
- **Блок 1 (Триада смысла):** 🎯 **Для чего и что сделано** (1–2 предложения цели + факты внутри: файлы, SHA, тесты, PID) · 💎 **Зачем** (польза) · ⏱️ **Почему сейчас** (триггер). Запрещено дублировать список сделанного в отдельных главах.
- **Блок 2 (Чекпойнт и CKS):** Курсор плана в 1 строку; таблица (SHA/Ветка · Сервисы · Метрики SLO vs Факт · Гейты G0–G4); аудит CKS 6/6 PASS строго 1 строкой: `🛡️ Аудит CKS (6/6 PASS): bias · leakage · confusion · complexity · alternatives · ssot — отклонений нет`.
- **Блок 3 (Горизонт решений):** Индекс `[Класс A/B/C - X/Y/Z]`, суть, «Что даст сразу», «Цена откладывания». Обязательная опция: `[▶️ Выполнить всё по очереди под MTD]` (активируется по «да», «всё», «mtd»). `/del` предлагается только при длине диалога >15 ходов.

## 3. Ключевые инварианты флота
1. **Gate Владельца (Merge Invariant):** Никогда не делать merge в `main` без прямой команды владельца: `mtd`, `MTD` или `мтд`.
2. **Безопасность данных (Safe Sync Gate):** `PRIVACY > SECURITY > DATA_INTEGRITY > KNOWLEDGE > AUTO-SYNC`. При ошибке — STOP.
3. **Методология:** Роли `HARVESTER` -> `DESTROYER` -> `SEALER`. Эпистемическая честность: `UNKNOWN != PASS`.
4. **On-Demand детализация:** Полные кодексы CKS, Sidecar-паспорта (`BPR40_SIDECAR_PASSPORT/1.1`), доставка метрик (`\\.\pipe\fleet_metrics`), матрица владения навыками и bubble-up предложений суб-агентов читаются по требованию из навыка [bpr5-protocol](file:///C:/Users/alexa/.gemini/config/plugins/fleet-bpr5-protocol/skills/bpr5-protocol/SKILL.md) или ядра `CORE.yaml`.
