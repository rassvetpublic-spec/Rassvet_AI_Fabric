# RAiF 10.3 — MTD 011011: интеграционный кандидат и gate PR

**Режим:** `OWNER_AUTHORIZED_STAGING_ONLY / DRAFT_PR / NO_MAIN_MERGE`.
**Дата:** 2026-10-10.
**Разрешение владельца:** `MTD 011011` на создание интеграционной ветки и PR в `main` и согласование внутренних документов. Это **не** разрешение на сам merge в `main`, force push, изменение CONTROL TOWER, BPR40/Router, CKS или аккаунтов.

## Точные источники
- `main`: `b18f31cb39bd655c7fd7e50466069f23d29c957a`.
- `AG_pather`: `5e6ef89e5aa9f5799d1a078d9fb3f0e45ba82520`.
- Core bounded Git: `8851de60b550389790e2c514589b968ff1185369`.
- Core handoff: `a5c4e6d2be35588cc875ae070566e3d39baed8d5`.
- Git tree Core union: `9236cd3fb21a39df01cf4586e34025dc75ff7295` (readback совпал).
- 288-file proposal tree до R5: `b31a8b7fe2d48c0a726a8160e0bc8e48d132223d` (readback **точно** совпал с Windows R1).
- Git tree проверенной исполняемой R5-проекции: `7edc560df8f664f8544c356d8b29f34ebb004903`. Единственное отличие от предыдущего дерева: `scripts/run-tests.ps1`, Git blob `1fdf6e2e8a089e7ae8b5f6fe7416b3083ec3010c`, SHA-256 `d2cf4438295eefb6c128030aa4f8a8c0b0eebfffc07bb26fb7c14b1f42370315`.

## Доказательства QA и границы
- Windows RESULT: `RAiF-10.2C-R5-RESULT.zip`, SHA-256 `6ff13ffbc04310200743f52e702c32ec53d2169990f328fa39959c8cfdda91d7`.
- Временное объединённое дерево после патча R5: **428/428 unittest PASS, 0 failures/errors/skips**, очередь и Codex-mock PASS.
- Git `main` на пользовательском Windows не был изменён исходным QA; проверка по host fingerprint.
- В состав staged-кандидата включены все изменения двух Core-веток и AG; три ранее конфликтных файла `docs/ROADMAP.md`, `scripts/demo.ps1`, `scripts/run-tests.ps1` имеют детерминированное разрешение. `.gitignore` объединён без потери обеих сторон.
- Отдельный документационный слой изменяет **только** `AGENTS.md`, `docs/PRODUCT_SCOPE.md`, `docs/ROADMAP.md`, `design/RFC_ACCOUNT_SWITCH_MECHANICS.md`. Documentation tree перед добавлением этого чекпойнта: `4a0ee150d649f71bb4b4898183ef5b62a4ec5b22`.
- Внутреннее направление Owner APPROVED, но `provider eligibility`, живое переключение идентичности, side effects, in-flight replay и реальные задержки **НЕ ПРОВЕРЕНЫ**.
- После изменения документации результат Windows 428/428 нельзя автоматически выдавать за полный PASS точного итогового PR tree. Требуется независимая QA-верификация текущей ветки; проверены статические точные строки `test_russian_language` и соответствие кода R5 по Git SHA.
- Не запускать повторно Codex 10.0B, CI без нужды; автоматические GitHub workflow на PR, если включены, учитывать отдельно.

## Следующий gate
`RAI-FABRIC/10.3-PR_INDEPENDENT_QA` → по результатам `RAI-FABRIC/10.3-SEPARATE_OWNER_MERGE_MTD`.

`main` не менять до нового явного подтверждения на конкретный PR, SHA и QA. Issue #1/#2/#3 не закрывать без собственных критериев завершения. Google Drive CONTROL TOWER и GitHub Tower PR #29 остаются отдельными контурами.
