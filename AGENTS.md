# BPR5 NextGen Micro-Core (v5.1.0-alpha / R3.3)
1. **Boot:** Заголовок первого ответа: `[BPR5-NEXTGEN: BOOT_ACTIVE | PROTOCOL: v5.1.0-alpha / 5.0.0-rc.1 | STATUS: SESSION_BOUND | MODE: <ТЕКУЩИЙ_РЕЖИМ>]`
2. **Триада смысла и вывод:**
   - Блок 1: 🎯 what_for+proof · 💎 why_benefit · ⏱️ why_now.
   - Блок 2: Курсор 1 строка; таблица (SHA, Services, SLO vs Fact, Gates G0-G4); CKS 6/6 PASS 1 строка.
   - Блок 3: Горизонт [Класс A/B/C - X/Y/Z] + `[▶️ Выполнить всё по очереди под MTD]`. Безопасный выход `/del` только >15 ходов.
3. **Инварианты флота:**
   - 1. Merge Gate: никогда не делать merge в `main` без команды `mtd`/`MTD`.
   - 2. Safe Sync Gate: `PRIVACY > SECURITY > DATA_INTEGRITY > KNOWLEDGE > AUTO-SYNC`.
   - 3. Роли: `HARVESTER` -> `DESTROYER` -> `SEALER`. `UNKNOWN != PASS`.
4. **On-Demand модули и спецификации:** Модули m01-m20, паспорта sidecar, метрики и bubble-up предложений читаются по требованию из навыка [bpr5-protocol](file:///C:/Users/alexa/.gemini/config/plugins/fleet-bpr5-protocol/skills/bpr5-protocol/SKILL.md) или ядра `protocols/bpr5/BPR5/CORE.yaml`.
5. **Политика CI/CD:** Windows-only CI, не запускать CI на каждом commit.


<!-- FLEET_AGENT_AUTONOMY_POINTER_R1 -->
## Fleet agent interoperability / самостоятельный QA (candidate)
После принятия Rules Hub PR [#124](https://github.com/rassvetpublic-spec/rassvet-rules-hub/pull/124) всем участникам проекта применять единый [FLEET_AGENT_AUTONOMY_INTEROP/1](https://github.com/rassvetpublic-spec/rassvet-rules-hub/blob/main/skills/FLEET_AGENT_AUTONOMY_INTEROP.md): **сами** передавать QA-COMMAND/ACK/RESULT и проводить разрешённые Windows QA через Antigravity/host tools, не просить владельца пересылать сообщения или запускать пробы. Если исполнитель недоступен — сохранить BLOCKED с доказательствами и следующим machine-owned курсором; UNKNOWN != PASS. Это *указатель*, не отдельная власть: Project Instructions, проектный QA_PROTOCOL, безопасность, MTD и protected gates имеют приоритет. Никакого автоматического live network/system mutation.
<!-- /FLEET_AGENT_AUTONOMY_POINTER_R1 -->
