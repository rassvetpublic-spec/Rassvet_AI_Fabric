# RAiF W2 / F2.0 — ledger + owned Windows children, candidate handoff

**Дата:** 2026-10-12. **Base:** `main@34e5f83652b65a4924fb48ff5aeeb90dde2783a7`, Git tree `c8dd1691ffc04f937a0d2f14600925f4b890b5ae`. **Статус:** `SOURCE_CANDIDATE_STAGED / WINDOWS_CI_PENDING / INDEPENDENT_QA_PENDING / OWNER_MERGE_MTD_CLOSED`.

## Преемственность и scope

[PR #5 merged](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/5), main Windows [CI #38185243827](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38185243827) `481/481 PASS`, post-merge receipt записан отдельно в `AG_pather@6a97a7d7...`. Не путать успех прежних тестов с проверкой новых W2 файлов.

## Состязательные правила

- Никакой произвольный `requeue` после task, имевшего внешний ledger effect, независимо от длины acknowledgment.
- Одноразовый fence активной аренды; `MAY_HAVE_RUN` означает **мог** сработать, но не доказательство запуска. Потеря ACK после фиксации в другом SQLite-файле → `UNKNOWN_OUTCOME` и `BLOCKED`; никакого автоматического повтора.
- `NO_EFFECT_VERIFIED` разрешён только когда effect остался `PREPARED` и dispatch никогда не допускался. Пустой target readback после `MAY_HAVE_RUN` остаётся `BLOCKED_RECONCILE`. Receipts синтетические, не externally signed.
- Windows Job Object получает процесс через `CREATE_SUSPENDED`, задание owned Job до `ResumeThread`; timeout убивает собственный Job и проверяет `ActiveProcesses=0`, не PID чужой IDE.
- У schema v2 нет runtime adapter для Antigravity/Codex: внешние попытки `run_one` отклоняются **до claim**. Обычные schema-v1 `mock/codex-mock` продолжают использовать старый контракт.

## План проверок

`tests/test_w2_effect_ledger.py`: 26 тестов (два независимых SQLite соединения, subprocess lost ACK, lease fencing, конфликт intents, receipt immutability, opt-in migration guards, synthetic readback, no requeue, no external adapter). `tests/test_w2_windows_owned_job.py`: 7 тестов, из них 5 Windows process/job scenarios. Статусы этих новых тестов **NOT_YET_RUN** до CI на точном W2 HEAD. `docs/W2_DURABLE_EFFECT_LEDGER.md` фиксирует эксплуатационные границы.

## Гейты

1. Единственный плановый GitHub-hosted Windows CI exact HEAD; проверить full unittest + 2 offline mock.
2. Независимая QA по точному diff и crash/ACK/Job Object. В случае CI FAILURE: исправлять обнаруженный конкретный дефект в той же ветке, не объявлять PASS.
3. Отдельный host `D:\` synthetic W2 RESULT, без старого `C:\GIT\Rassvet_AI_Fabric` (134 WIP) и без реального провайдера.
4. Отдельное owner MTD для merge W2 только по проверенному SHA.

**Cursor:** `RAIF/W2_F2_1_WINDOWS_CI_THEN_INDEPENDENT_QA`. W2 полного production release пока нет.
