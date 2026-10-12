# RAiF W2 F2.1 — точный Windows CI 514/514, QA ожидается

**Дата:** 2026-10-12. **Source:** [DRAFT PR #8](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8) `b36cfbc0850b5f49327162133a2a4840ba82e1ee`, Git tree `06f511d0dd6a9a0984040aeefb82a928a90467c1`, parent `34e5f83652b65a4924fb48ff5aeeb90dde2783a7`. **Сохранённый контур:** `main` не менялся, старые 134 WIP на Windows не тронуты.

### Доказано логом на точном SHA

[GitHub-hosted Windows #38186544803](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38186544803), job `114609976272`: `completed / success`; **514 тестов, 514 PASS за 33.317s**, `OK`. Шаги preflight, SQLite mock, Codex-mock — все PASS. Полный BPR40 реестр в кандидатном дереве: **46 Python modules + 46 sidecar passports**.

В журнале явно выполнены все 26 проверок ledger и все 7 тестов Windows Job Object, в том числе: две конкурирующие SQLite-сессии на один dispatch; настоящий второй локальный Python-процесс пишет в независимый SQLite sink, после чего recovery не повторяет side effect; immutable receipt после reopen; timeout-owned-job завершается без активных descendants; реальный внешний runner блокируется до claim в schema v2.

### Ограничения

**Это F2.1-кандидат, не production приемка.** Тестовые receipts не являются подтверждением удалённого target. `MAY_HAVE_RUN` не даёт автоматически no-effect; отсутствие ACK → UNKNOWN_OUTCOME/BLOCKED. Реальный Windows host владельца **NOT_RUN**; hardware power-loss/TOCTOU, реальный JobObject worker, внешние Antigravity/Codex эффекты **NOT_VERIFIED/NOT_IMPLEMENTED**.

QA запрошена в [issuecomment #6115408037](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/8#issuecomment-6115408037): независимый R4 для PR #8 на конкретном SHA, **не** повторная облачная проверка CI. Merge и снятие DRAFT запрещены до отдельного QA/MTD.

### Маршрут

`--`: P0/P1 от QA корректировать только в PR-ветке с точным контрпримером.
`==`: не перезапускать уже зелёный CI без изменения source.
`++`: `RAIF/W2_F2_1_INDEPENDENT_QA_PENDING` → `W2/F2_2_OWNER_HOST_SYNTHETIC_LOST_ACK_AND_JOB`.
`~~`: нет Tower/Router/CKS/BPR40/G2 authority writes; state PR8 лишь проектная кандидатная запись.

Данный файл является отдельным **post-CI** receipt и не подменяет pre-CI `s15` с `NOT_RUN`. Оба честно описывают состояние на момент создания.
