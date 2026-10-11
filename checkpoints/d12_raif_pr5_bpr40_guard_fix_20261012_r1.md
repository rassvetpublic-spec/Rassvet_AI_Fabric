# RAiF PR #5 — BPR40 паспортные контракты: одна завершающая поправка

**Дата:** 2026-10-12. **Область:** только ветка PR #5 `raif-10-4-ag-delta-20261010`, от точного merge коммита `6a0e58ed3ac31ebf7f90ffb590ba0aa0f18f814e` (tree `bd9498903b2f01222ec11a8a1a9bde6674a30170`), актуальный `main@9fb3d35b74915db1801f44743c22e5f79a3c979d`.

## Уже подтверждённое, не дублировать

- Исходная интеграционная QA [результат](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/pull/5#issuecomment-6114945487) предложила merged tree, материализованное до нашего шага.
- Отдельный concurrent integration commit `6a0e58ed3ac31ebf7f90ffb590ba0aa0f18f814e` уже внедрил 44-й паспорт, `unittest` вместо `pytest`, сохранил версии `host_diagnostic` и `continuity` и прошёл [Windows CI #38183665331](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38183665331): **470/470 PASS**, preflight + mock + Codex-mock.
- Следовательно, новый PR или второй полный синтетический прогон старого дерева не нужен.

## Что осталось исправить в том же PR #5

- P2 PR #7: валидатор не проверяет `schema`, ошибочно принимает P1-violations, игнорирует variadic `*args/**kwargs`, а `--enrich-functions` может стереть повреждённый паспорт.
- Несогласованная версия: `rai_fabric.__version__=1.0.0` против distribution `pyproject.toml=0.1.0`. Сохраняем опубликованную `0.1.0`, синхронизируем `rai_fabric/__init__.py` и `__init__.passport.json`.
- Обновляем четыре затронутых sidecar AST args (host_gate, worktree_review, accounts_cli, native_rpc).
- 4 паспортных `unittest` сохраняются, тестовый файл расширен до 15, с отрицательными проверками валидатора, схемы, `module_id`, variadic и сохранения невалидного JSON.

## Доказательная сила и ограничения

После commit нужна одна новая Windows CI на *новом точном SHA*, а затем новая независимая delta QA. Предыдущие `470/470` не доказывают эту поправку. Нет реальных provider calls, user-host acceptance, powerloss или target side-effect ledger.

**NO_MAIN_MERGE:** PR #5 OPEN/DRAFT, отдельный owner MTD нужен после CI/QA. `C:\GIT\Rassvet_AI_Fabric` (134 WIP) не трогать, AG_pather/Tower/CKS/Router/BPR40 authority не изменять.

**NEXT CURSOR:** `RAIF/10.4_PR5_BPR40_P2_HARDENING_WINDOWS_QA`.
