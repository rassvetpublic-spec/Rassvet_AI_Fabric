# CP-54A1: минимальный наблюдатель Native Connect RPC (без AG-tools)

Дата: 2026-10-10, ветка AG_pather. Кодовый этап, статус WINDOWS_CI_PENDING.

## Реализовано
- src/raif_ag_supervisor/native_rpc.py: LocalRpcTarget только для 127.0.0.1, проверенный port, in-memory CSRF (repr не содержит секрет), POST Connect JSON только для HasAuthToken и GetAuthStatus; фиксированный URL, тело {}, timeout <=10 sec, ответ <=16KiB, ни redirects, ни произвольных методов, ни прямых Google/OAuth вызовов.
- Ответ строго сокращается до булевых флагов и безопасных кодов ошибок; токены, project_id, email, raw JSON не возвращаются ни через NativeRpcObserver.observe(), ни через исключения.
- Отчёт помечает has_valid_auth как UNTRUSTED: реальный Language Server прошёл CP-31 binary patch, значение этого флага не является независимым свидетельством реальной авторизации.
- tests/test_native_rpc.py: 16 synthetic-only tests: rejection remote host, плохих CSRF, портов, мутирующих методов, timeout, oversized responses, redirects, unsafe payload/stack errors и доказательство отсутствия секретов в отчёте.
- В локальной среде подготовки: 16/16 тестов PASS и py_compile PASS.
- Никаких новых изменений native credentials, процесса Language Server, исходных пользовательских файлов, AG-tools или CP-31 binary нет.
- Реальные RpcTarget(port, csrf) и транспорт HTTP/Connect v1 ещё не проверены на RASSVET_DESKTOP. Этого не надо утверждать без host-result.

## MERGE-PREFLIGHT 10.1A (GitHub data only)
- main=b18f31cb39bd655c7fd7e50466069f23d29c957a.
- 10.1=a0daf08375b70d202b3dc7b5ab51f894e87d9ae0 (ahead 1, behind 0).
- 10.1A=381754c5eaf13ff89bf0ada38431ad4f35e17350 (ahead 2, behind 0), включает 10.1.
- AG_pather на момент readback=5b88b4022451b155e3f3b2872fc051213e47cffa, относительно main ahead 121/behind 34.
- Полные git trees сравнивались относительно общего merge-base 95122c90a4ac684e0ffba8b493001f7c4797d15a. Изменения main и AG_pather пересеклись в 4 путях: .gitignore, docs/ROADMAP.md, scripts/demo.ps1, scripts/run-tests.ps1.
- Дополнительные 11 путей между main и 10.1A НЕ пересекаются с изменёнными AG_pather путями (по blob SHA), но это только file-level preflight, не выполненный git merge-tree/Windows smoke.
- .gitignore различается в непересекающихся дополнениях (DPAPI exclude в main, RAiF runtime results в AG); вероятно автоматически совместим, но нельзя утверждать без git merge-tree. ROADMAP отличается и по смыслу.
- Никакие ветки main/10.1A не менялись. FF/push, merge, удаление веток и QA на пользовательском Windows не выполнялись.

## Курсоры
AG_pather → CP-54A1 NATIVE_RPC_CODE_TESTS → CI_READBACK → CP-54A2 SINGLE_WINDOWS_READONLY_RPC_PROBE (no secret output);
RAI-FABRIC/10.1A → MERGE_REHEARSAL_IN_DETACHED_TEMP_WORKTREE → COMBINED_WINDOWS_QA → MERGE_APPROVAL.
