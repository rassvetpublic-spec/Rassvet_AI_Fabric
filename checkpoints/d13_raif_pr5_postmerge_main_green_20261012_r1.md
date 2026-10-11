# RAiF 10.4 — PR #5 post-merge readback и аудит ограничений

**Дата фиксации:** 2026-10-12. **Статус:** `MERGED_MAIN_VERIFIED / WINDOWS_CI_481_PASS / POSTMERGE_RECEIPT`. Это checkpoint в `AG_pather`, **не** новая authority Башни и не разрешение на следующий merge.

## Доказанное GitHub
- [PR #5](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/5): `MERGED`, 2026-10-11 23:41:42 UTC, участник `rassvetpublic-spec`.
- `main@34e5f83652b65a4924fb48ff5aeeb90dde2783a7`: родители `9fb3d35b74915db1801f44743c22e5f79a3c979d` и `e9e117d22c89f6daf54783de34ac7493c4486641`, дерево `c8dd1691ffc04f937a0d2f14600925f4b890b5ae`, **совпадает с точным R4-деревом кандидата**.
- [Windows Actions после merge #38185243827](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38185243827): `SUCCESS`; точный лог `Ran 481 tests in 28.386s`, `OK`, Windows preflight, SQLite mock, Codex-mock PASS.
- Предыдущая PR CI [#38183921505](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38183921505): `481/481 PASS` на предшественнике `e9e117...`.

## Качество доказательств: не замалчивать расхождение
- Пользователь предоставил текст `RAIF-PR5-BPR40-R4-QA_RESULT/1`: `QA_PASS_WITH_SCOPE`, `evidence_sha256=64eda573751f3ecf5de7230807ec7c1da4fc903a6f016fc572c1b01f270362b9`.
- Этот SHA256 **не совпадает** с фактическим хешем указанного `checkpoints/s12_raif_pr5_bpr40_guard_fix_20261012_r1.json`: `dac9e64222ddf209141b4c2cd4ff1f8edd3b38ca193056314e17e829c6180f25`. Git blob `f4e2e35073350f4ad6c41d7af3fb5c647599fdb6`.
- `s12.json` является *pre-CI* плановым checkpoint (поля `NOT_RUN`), а не подписанным фактическим `QA_RESULT`. Отдельного R4 QA review и MTD-артефакта в переписке PR не найдено; факт слияния аккаунтом владельца подтверждён GitHub event. Без дополнительного независимого сертификата эти границы не подменять выдуманной аттестацией.

## Не подтверждено
`HOST_R3_NOT_RUN`, реальный внешнесистемный ACK/reconciliation, Windows Job Objects для всех owned descendants, hardware powerloss, подтверждение действий GDrive Tower/CKS. W1 host acceptance на старом SHA не переносится на R4 автоматически.

## Далее — W2

Источник дизайна: `AG_pather/design/d02_raif_10_4_durable_recovery_w2_20261010_r1.md`. Разрабатывать только от свежего `main@34e5f836...` в новой review-ветке. Никаких live provider-операций. На базе `FabricStore.atomic` и `lease_epoch` создать opt-in `effect_operations` и `effect_receipts`, `MAY_HAVE_RUN → UNKNOWN_OUTCOME` при потере ACK, запрет blind requeue, отдельный Windows owned child Job Object. Важные gates: isolated SQLite file-backed tests, Windows CI, независимая QA, отдельный MTD на новое PR.

**Курсор:** `RAIF/W2_10_4_EFFECT_LEDGER_AND_OWNED_PROCESS_HARDENING`. `main` и старый `C:\GIT\Rassvet_AI_Fabric` (последний отчёт: 134 WIP) не трогать.
