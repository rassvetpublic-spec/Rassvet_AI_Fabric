# RAiF / BIGWAVE 02 — проектная передача после readback Башни и GitHub

**Дата:** 10 октября 2026. **Readback:** `2026-10-10T08:28:59.177084Z`. **Владелец:** `rassvetpublic-spec/Rassvet_AI_Fabric`, `AG_pather`. **Исходный HEAD до нового документационного коммита:** `5c602c7617ca051dcbc3f9c6705b8384882c3cdc`.

## 1. Отправная точка (не повторять готовое)
- Код BIGWAVE R1 (5 модулей + 5 файлов тестов) `4e801c6e8a6ef1c854f3f2df9f81bbe678070d2e`; итоговая принятая документация на `5c602c7617ca051dcbc3f9c6705b8384882c3cdc`. Один стандартный [Windows CI #38037038411](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38037038411) подтвердил `SUCCESS 237/237` на точном кодовом коммите. Этот CI **не тестировал merge-дерево** и не доказывает живой OAuth/rollback.
- Проверен оригинальный архив `RAiF-BIGWAVE-RESULT_20261010_080311_c4f3d96c.zip`: SHA-256 `692658196fd42031633c4ba56c3c4e906a9f9ef63e12e78291df2a5efc7854b4`, CRC PASS, 5 разрешённых файлов; 8/8 зарегистрированных этапов `PASS`; синтетика Windows `47/47`, 0 errors/failures/skips.
- Точное различие: строка `FABRIC_PREFLIGHT_READONLY/PASS` в `STEPS.jsonl` означает успешное *завершение ограниченного наблюдения*, а не состояние клона; `report.json.fabric_preflight_verdict = HOST_CLONE_READ_FAILED`. Поэтому `Fabric 10.1B = HOST_NOT_ACCEPTED`, 20 targeted, full и mock проверки не выполнялись.
- CP54C1 rollback и CP54D continuity получили **только synthetic PASS**. Активный Google identity не подтверждён, ни один из 9 opaque VAULT IDs не привязан к живой сессии; `hot_swap/inflight_resume=NOT_TESTED`. Не повторять CP31/46/52D/54A5/B1/B3, Codex 10.0B, прошлый BIGWAVE.

## 2. GitHub / интеграция
- `main=b18f31cb39bd655c7fd7e50466069f23d29c957a`, `AG_pather=5c602c7617ca051dcbc3f9c6705b8384882c3cdc` (до документационного коммита); `raif-10-1a-clone-handoff-20261010=a5c4e6d2be35588cc875ae070566e3d39baed8d5`. Эти ветки не слиты. Issues [#1](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/1), [#2](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/2), [#3](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/3) остаются **OPEN**.
- CONTROL TOWER: [PR #29](https://github.com/rassvetpublic-spec/CONTROL_TOWER/pull/29) **OPEN/DRAFT/NONCANON**, закреплён на историческом CP54B2. Действующая authority в Google Drive принадлежит USER; GitHub Tower не production-synced. Подробное readback в `RAIF_TOWER_GITHUB_READBACK_2026-10-10_R1`.
- Документационный конфликт: `AGENTS.md` запрещает автоматическую ротацию потребительских аккаунтов ради обхода квот, а `docs/PRODUCT_SCOPE.md` и `design/RFC_ACCOUNT_SWITCH_MECHANICS.md` описывают/утверждают такую цель; `docs/ROADMAP.md` одновременно содержит старое отрицание. Оставить **DOC_SCOPE_CONFLICT / DECISION_REQUIRED**. Внутреннее одобрение RFC не доказывает соблюдение условий внешнего поставщика. Не менять документы или аккаунты по умолчанию.

## 3. Следующая укрупнённая безопасная волна
1. `BIGWAVE_02 / READONLY_HOST_CLONE_DIAGNOSIS` — установить точный безопасный код причины `HOST_CLONE_READ_FAILED` для существующего `C:\GIT\Rassvet_AI_Fabric`: проверить существование .git, origin, HEAD, ref pin, тип каталога, ACL и чистоту **только чтением**. Запрещены blind clone, reset, pull, checkout, force, stash и подмена пользовательского дерева.
2. `Fabric 10.1B / WINDOWS_HOST_ACCEPTANCE` — после положительного preflight выполнить на изолированном exact-pin дереве targeted 20, весь набор offline и mock. `HOST_PASS` только по фактическому Windows RESULT, не по prior CI и не по 47 синтетике.
3. `CP54D / FAULT_INJECTION_HARDENING_OFFLINE` — расширить отрицательные тесты crash/lock/replay/idempotency; одна совмещённая пачка исходников, один CI после изменений и один Windows ZIP+PS1 при необходимости. Все новые runtime/RESULT только `D:\ЗАГРУЗКИ`.
4. `G2 identity` остаётся `CP54B3/EXPLICIT_IDENTITY_READ_GATE_CLOSED`. Живой `GetUserStatus`, операции Credential Manager, переключения 2→5 и rollback требуют дополнительных индивидуальных gates. `Issue-3 DETACHED_MERGE_REHEARSAL` допускается только после QA и отдельного merge gate.

## 4. Курсор и граница полномочий
**Завершено:** `AG_pather / BIGWAVE_R1_WINDOWS_CI_237_PASS + TOWER_GITHUB_READBACK`.

**Следующий курсор:** `AG_pather / BIGWAVE_02_READONLY_HOST_CLONE_DIAGNOSIS_PLUS_CP54D_OFFLINE_FAULT_HARDENING`.

**Параллельный:** `Fabric / 10.1B_READONLY_HOST_CLONE_DIAGNOSIS_THEN_PINNED_TARGETED_FULL_MOCK_WINDOWS_QA`.

**Интеграция:** `ISSUE-3/DETACHED_MERGE_REHEARSAL_AFTER_QA`. Изменений `main`, Tower authority, BPR40/Router, CKS Canon или Google-аккаунтов — **0**.

**Следующий чат:** читать этот MD/JSON вместе с проектным `RAIF_TOWER_GITHUB_READBACK_2026-10-10_R1` и точным новым HEAD после readback, не возвращаться к устаревшему Tower CP54B2 pointer.
