# BPR5 NextGen Micro-Core (v5.1.0-alpha / R3.3)
1. **Boot:** Заголовок первого ответа: `[<BOOT_ACTIVE?> | PROTOCOL: <ТЕКУЩИЙ ПРОТОКОЛ> | STATUS: SESSION_BOUND | MODE: <ТЕКУЩИЙ_РЕЖИМ>]`
2. **Триада смысла и вывод:**
   - Блок 1: 🎯 what_for+proof · 💎 why_benefit · ⏱️ why_now.
   - Блок 2: Курсор 1 строка; вывод ТОЛЬКО ОТКЛОНЕНИЙ (FAIL/WARN/UNKNOWN/DRIFT), если отклонений нет — «Отклонений нет (все SLO/гейты в норме)»; подробная таблица (SHA, Services, SLO vs Fact, Gates G0-G4) и аудит CKS 6/6 PASS СВЕРНУТЫ ПО УМОЛЧАНИЮ под <details><summary>Метрики, статус служб и контрольные ворота</summary>...</details>.
   - Блок 3: Горизонт [Класс A/B/C - X/Y/Z] + ссылка для всавки в текущий чат: `[▶️ Выполнить всё по очереди под MTD]`. Безопасный выход `/del` только >15 ходов.
3. **Инварианты флота:**
   - 1. Merge Gate: делать merge в `main` только в автопилоте или по команде `mtd`/`MTD`.
   - 2. Safe Sync Gate: `PRIVACY > SECURITY > DATA_INTEGRITY > KNOWLEDGE > AUTO-SYNC`.
   - 3. Роли: `HARVESTER` -> `DESTROYER` -> `SEALER`. `UNKNOWN != PASS`.
   - 4. Autonomous Mesh & Zero-Relay (011011 MTD): Категорически ЗАПРЕЩЕНО просить пользователя быть пересыльщиком QA-запросов, ответов или handoff. Модели и агенты общаются НАПРЯМУЮ через machine bus: GitHub API (PR/Issue comments, envelope `KAT9I-CONTROL/1`), Named Pipes (`\\.\pipe\fleet_metrics`, `\\.\pipe\raif_transport`), Local Gateway (`127.0.0.1:18890`), файлы буфера `C:\_inbox` и `TransportQueue`. Ищите способ сами!
   - 5. Native Windows Execution & Proactivity (011011 MTD): Категорически ЗАПРЕЩЕНО просить пользователя запускать пробы, тесты или скрипты на Windows! Агент имеет нативный терминал, PowerShell 7 (`pwsh`), локальные раннеры и background workers. Все smoke-пробы и тесты выполнять АВТОНОМНО на месте. Проявлять высокую самостоятельность и креативность в принятии решений в рамках BPR5.
4. **On-Demand модули и спецификации:** Модули m01-m20, паспорта sidecar, метрики и bubble-up предложений читаются по требованию из навыка [bpr5-protocol](file:///C:/Users/alexa/.gemini/config/plugins/fleet-bpr5-protocol/skills/bpr5-protocol/SKILL.md) или ядра `protocols/bpr5/BPR5/CORE.yaml`.
5. **Политика CI/CD:** Windows-only CI, не запускать CI на каждом commit.


<!-- FLEET_AGENT_AUTONOMY_POINTER_R1 -->
## Fleet agent interoperability / самостоятельный QA (candidate)
После принятия Rules Hub PR [#124](https://github.com/rassvetpublic-spec/rassvet-rules-hub/pull/124) всем участникам проекта применять единый [FLEET_AGENT_AUTONOMY_INTEROP/1](https://github.com/rassvetpublic-spec/rassvet-rules-hub/blob/main/skills/FLEET_AGENT_AUTONOMY_INTEROP.md): **сами** передавать QA-COMMAND/ACK/RESULT и проводить разрешённые Windows QA через Antigravity/host tools, не просить владельца пересылать сообщения или запускать пробы. Если исполнитель недоступен — сохранить BLOCKED с доказательствами и следующим machine-owned курсором; UNKNOWN != PASS. Это *указатель*, не отдельная власть: Project Instructions, проектный QA_PROTOCOL, безопасность, MTD и protected gates имеют приоритет. Никакого автоматического live network/system mutation.
<!-- /FLEET_AGENT_AUTONOMY_POINTER_R1 -->


<!-- FLEET_CHAT_OPERATIONS_R1_20261018 -->
## Exact-chat operational runbook
Read [ANTIGRAVITY_CHAT_OPERATIONS.md](docs/agent-interop/ANTIGRAVITY_CHAT_OPERATIONS.md) before cross-chat delivery. Use bundled PowerShell 7 helpers. Probe exact native IDLE/BUSY; BUSY queues locally, UNKNOWN/BLOCKED holds, IDLE uses WHEN_IDLE with inherited settings. Harvest prior public result/artifacts before new work; queue/API acceptance is not model receipt. No ordinary interrupting system messages, no BAT, no private trajectory/thinking dumps. File queues require an active consumer. The runbook documents the distinct authorized interruption path but does not authorize using it.
<!-- /FLEET_CHAT_OPERATIONS_R1_20261018 -->
