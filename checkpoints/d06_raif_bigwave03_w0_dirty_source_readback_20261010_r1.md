# RAiF W0 — реальный Windows readback; WIP сохранён

Дата 2026-10-10. Владелец: `rassvetpublic-spec/Rassvet_AI_Fabric`, ветка `AG_pather` на входе `edee65158c384ac65c4c27051f545d5dfcb16ee7`. Проектный информационный checkpoint без переноса authority, merge или CI.

## Результат пользовательского W0

Получен `RAiF-W0-RESULT_20261010_130242_acf64a51.zip`, SHA-256 `72a5951a824d65b34e279d44c812e769269ae5a26b348fb2e04bb2e28fbc5d64`. ZIP CRC PASS, ровно пять ожидаемых файлов. `RECEIPT.json` и `report.json` согласованы: 5 этапов PASS, 1 BLOCKED, общий `PARTIAL / SOURCE_WORKTREE_DIRTY`; 9 локальных read-only Git вызовов, 0 reported changes/network/provider/account operations.

- Git: `C:\Program Files\Git\cmd\git.exe` доступен, его SHA-256 `78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f`; version check PASS. Прежняя ошибка `GIT_EXECUTABLE_MISSING` относилась к PATH Python и закрыта **в рамках fixed-path**.
- Исходный каталог `C:\GIT\Rassvet_AI_Fabric` — нормальный Git clone с допустимым origin. HEAD стабилен в двух чтениях: `b18f31cb39bd655c7fd7e50466069f23d29c957a`, историческая база main до 10.3.
- `clone_clean_tracked_untracked=false`: **грязный WIP**. `clone_ignored_files_absent=true`, `clone_hidden_index_flags_absent=true`.
- Текущий `main` по GitHub: `8dc6ee32eabd3334012763bac8e641f682e478c6`. Он не равен локальному HEAD. `exact_main_10_3_pin_ready=false`.
- **W1 Fabric 10.3 host QA = NOT_RUN**. Ни код локального WIP, ни его файлы не следует автоматически стирать, stash, rebase, checkout или исправлять.

## -- Критическая корректировка прежнего плана

`GIT_EXECUTABLE_MISSING` больше не blocker. Текущий blocker: **WORKTREE_DIRTY + OLD_LOCAL_HEAD**. Наличие старого HEAD само по себе не ошибка; каталог может быть сознательно зафиксирован до интеграции. Полный переход к W1 по этому каталогу не разрешён.

## == Исполнимый следующий шаг без мутаций

Подготовлен `Start-RAiF-BIGWAVE03-Reconcile-R1.ps1`, SHA-256 `94ef4280550087c66eed6c6cb29698bdea922ee0e7734204ad8ed4aaed15adf2`. Он **статически проверен; НЕ запускался на пользовательском Windows**.

Сохранить в `D:\ЗАГРУЗКИ`, запустить:
`pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\Start-RAiF-BIGWAVE03-Reconcile-R1.ps1"`.

Скрипт допускает только семь локальных Git-read calls, проверяет **тот же SHA git.exe**, считывает `git status --porcelain -z`, возвращает агрегированные счётчики tracked/staged/untracked/deleted/rename/conflict без имён файлов или их содержимого, обнаруживает локальный Git-объект точного main 10.3 и ссылку `refs/remotes/origin/main`, повторяет HEAD. Не делает fetch/clone/reset/stash/clean/checkout/merge/push, не отправляет credentials.

Один RESULT ZIP `RAiF-W0B-RESULT_<runid>.zip` только в `D:\ЗАГРУЗКИ` (5 приватно безопасных файлов).

## ++ Дальнейший маршрут в пределах MASTER PLAN

1. `BIGWAVE03/W0_RECONCILE_DIRTY_SOURCE_AND_CHECK_MAIN_OBJECT` — узнать тип WIP и доступность 10.3 локально, не изменяя WIP.
2. Сохранить локальный WIP как есть; если он нужен, выбрать **отдельный, новый, явно допущенный** изолированный source staging под `D:\ЗАГРУЗКИ` для exact main 10.3 (не worktree внутри существующего .git). Если exact source недоступен офлайн, network fetch только с отдельным разрешением.
3. `W1/10.3_POST_MERGE_HOST_QA` — pinned source, полный offline unittest, targeted worktree-review, SQLite queue, Codex mock, без повторения live 10.0B. CI 428/428 / 265/265 не повторять: это другой host gate.
4. `W2/10.4_CP54D_DURABLE_RECOVERY` — fault-injection/replay/durable checkpoint; затем W3 manual executor handoff, W4 5-domain read-only, W5 Windows release.

**Границы:** G2 identity CLOSED; Tower GitHub не authority (`production_sync=false`), BPR5 candidate not sealed. PR4 real merge подтверждён, отдельный MTD-merge evidence остаётся UNVERIFIED. Не трогать main, CONTROL_TOWER, Router, BPR40, CKS и аккаунты по факту чтения.

## Конец checkpoint
**Next:** `BIGWAVE03/W0_RECONCILE_DIRTY_SOURCE_AND_CHECK_MAIN_OBJECT`.
