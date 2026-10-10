# RAiF 10.4 — Postmerge AG Delta, read-only host and PR QA gate

**Дата:** 2026-10-10. **Owner route:** `RAI-FABRIC/10.4-POSTMERGE_ISSUE_AND_BRANCH_RECONCILIATION`.
**Статус до PR CI:** `STAGED_AG_DELTA / DOCUMENTS_RECONCILED / INDEPENDENT_WINDOWS_QA_PENDING`.
**Разрешение:** пользовательское `>>>>` продолжает ранее согласованную волну 10.4 (PR/QA), **не** является разрешением на фактическое объединение PR в `main`.

## Точная база, provenance и границы

- `main@8dc6ee32eabd3334012763bac8e641f682e478c6`, исходное Git tree `8d2a0d0c195a3ffbb64cf26ba46e906936261894`; PR #4 уже объединён; CI #38049976872 = Windows 428/428 PASS.
- `AG_pather@307909001ab826149f9ce9a9a67a286e18bfdb3a` содержит дополнительные checkpoint-only коммиты. Точные исполняемые байты новой BIGWAVE02-дельты равны `AG_pather@975c61a5b77ca69a674df994fbcab0d372c62ac9` (CI #38051697374: Windows 265/265 на AG-ветке; **не** объединённое дерево).
- Дельта source (проверить exact blob): `src/rai_fabric/host_diagnostic_10_3.py@facaf36d6a8bf6eefc32fc27aa944ab50bd6ef1e`, `src/raif_ag_supervisor/continuity.py@36dda2709a4994c3bc9f2d4843c58e3ee1448ac9`, `tests/test_bigwave02_host_diagnostic.py@675a514bc8f1784979a89da46a0cba2ccef72d52`, `tests/test_bigwave02_continuity_faults.py@508267849f883d0e6a0e4d1d7792f3d8b9304546`.
- Исходный код 10.4 имеет точный Git tree `ed37e8d230e4b66d39eee6471bea986b65a58283`, четыре изменённых пути относительно main (3 add + 1 modify).
- Два документа: `README.md` и `docs/ROADMAP.md` скорректированы согласно подтверждённым этапам без повышения runtime/authority заявлений.

## Новый факт W0/W1: не терять пользовательские изменения

- Проверенный W0B: `C:\GIT\Rassvet_AI_Fabric` содержит **134 tracked modified WIP**, локальный HEAD `b18f31cb...`, исторический `origin/main`. Не выполнять `checkout, pull, reset, stash, clean` или связанную worktree запись в этот .git.
- Новый D:-checkout `main@8dc6ee32...` уже дал **428/428 Windows PASS** (W1). Smoke `mock` и `codex-mock` остались не приняты в пользовательском W1 из-за ошибки harness (`task_id` вместо `id`); это не означает ошибки SQLite.
- Дальнейший пакет 10.4 создаёт НОВЫЙ каталог под `D:\ЗАГРУЗКИ`, не удаляет предыдущие D:-runtime/RESULT, и выполняет полную проверку только нового PR SHA + два mock-smoke с правильным контрактом.
- Указанные GitHub CI и host W1 результаты **разных** source pins. Не суммировать `428 + 265`, не объявлять PASS 10.4 до точного readback CI/RESULT.

## -- == ++ gates

- `--`: проверить 134 WIP, линейность source, отсутствие перемещения оригинального HEAD и исторические статусы Issue #1/#3; не рассматривать source Git object SHA как независимую подпись.
- `==`: через отдельный PR с тремя добавленными и одним изменённым Python-файлом доказать объединённую регрессию на Windows и две mock-проверки, без секретов и live RPC. Подтвердить финальный PR tree/blob.
- `++`: после QA/PR принять владельческое решение о merge и продолжить `RAI-FABRIC/10.5-DURABLE_WINDOWS_WORKER`. `AG_pather` сохранить; Git-история AG не становится parent автоматически от snapshot integration.
- `~~`: release route остаётся ориентированным на офлайн-fabric; AG live identity/provider eligibility, BPR5 promotion и Tower/CKS write находятся вне критического пути и за отдельными gates.

**ЗАПРЕЩЕНО ЭТИМ ЭТАПОМ:** автоматический merge, установка Windows Service, новый реальный Codex turn, identity/account-switch, Credential Manager write, внешние paid API, обновление CONTROL TOWER/Router/BPR40/CKS и очистка пользовательского checkout.

**Cursor:** `RAI-FABRIC/10.4-PR_INDEPENDENT_WINDOWS_QA` → `RAI-FABRIC/10.4-OWNER_MERGE_MTD_PENDING` или `10.4/BLOCKED_<EXACT_CODE>`.
