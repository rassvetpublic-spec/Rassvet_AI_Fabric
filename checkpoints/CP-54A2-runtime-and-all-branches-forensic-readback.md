# CP-54A2 — Windows RPC probe и карта всех веток Rassvet AI Fabric

Дата: 2026-10-10. Ветка публикации чекпойнта: AG_pather.
Метод: GitHub REST read-only tree/branch/compare/issues/actions + пользовательский обезличенный CP54A2 RESULT ZIP. Слияние, remote push в main, реальные аккаунты и процессы не изменялись.

## I. CP54A2: свидетельство с Windows

- Результат пользователя: `RAiF_AG_CP54A2_RESULT_20261010_080335_19c8d912.zip`; размер 2410 bytes; SHA-256 `268880022903ac54c0cbeeaa9ad76ccca9d06447a47737df863acfb9e17d3f0f`.
- ZIP CRC OK; allowlist: STATUS.txt, SUMMARY.txt, RECEIPT.json, STEPS.jsonl, report.json.
- Receipt: `RAIF_AG_CP54A2_NATIVE_RPC_READONLY`; status SUCCESS; exit_code=0; PowerShell 7; ZIP SHA verified. 38 событий: 18 start, 19 ok, **1 warning**.
- LS: один language_server PID 19972, start UTC 2026-10-10T04:53:07.2098966Z, stable_after_probe=true.
- Process commandline доступна только in-memory, CSRF argument found=true (значение не сохранялось).
- `find_only_language_server_owned_listening_ports`: warning `STAGE_FIND_ONLY_LANGUAGE_SERVER_OWNED_LISTENING_PORTS_UNAVAILABLE`. Обнаружено **0 слушающих TCP портов**, **0 попыток RPC**.
- `has_auth_token=MISSING_CSRF_OR_LISTENER`, `get_auth_status=NO_CONFIRMED_RPC_PORT`; булевы поля auth остаются null. Статус `SUCCESS` означает **успешное завершение диагностики**, не подтверждение работающего RPC.
- Изученный probe.ps1 использует `Get-NetTCPConnection -OwningProcess $pidCandidate -State Listen -ErrorAction Stop` и фильтрует IPv4 `127.0.0.1`/`0.0.0.0`. В случае отсутствия совпадений или исключения этот шаг маркирует warning. **Нельзя заключать**, что LS не имеет RPC: transport может быть иным, слушатель может быть в другом процессе, cmdlet мог завершиться с ошибкой. Конкретная причина пока не установлена.
- В отчёте: native_credentials_modified=false, raif_vault_accessed=false, antigravity_processes_modified=false, direct_external_provider_requests_sent=false, returned_secret_values=false, identity_verified=false, hot_swap_verified=false.
- Следующий технический этап: read-only транспортная диагностика с независимым способом поиска listener (например, bounded netstat/Win32 port table и безопасное извлечение ТОЛЬКО whitelist port args из локального процесса); не брутфорсить TCP, не отправлять CSRF в лог, не запускать mutating RPC; при отсутствии подтверждённого транспорта — честный `RPC_ENDPOINT_UNVERIFIED`. **Никакого нового ZIP до фиксации минимальной причины**.

## II. Remote GitHub: все 8 веток

| Branch | На момент readback SHA | Роль |
|---|---|---|
| `main` | `b18f31cb39bd655c7fd7e50466069f23d29c957a` | основной Fabric, 10.0B (первый реальный Codex turn) |
| `raif-10-1-worktree-offline-20261010` | `a0daf08375b70d202b3dc7b5ab51f894e87d9ae0` | frozen 10.1 offline Git worktree reviewer, pin 10.1 |
| `raif-10-1a-clone-handoff-20261010` | `a5c4e6d2be35588cc875ae070566e3d39baed8d5` | накопительная 10.1 + 10.1A + 10.1B scripts/host QA handoff (теперь 3 коммита относительно main) |
| `AG_pather` | `f8451817e18bc3edcc5a19f6637c8aa735a86d21` | независимый Antigravity Supervisor CP54A1/54A2; HEAD до данного документа |
| `pather` | `95122c90a4ac684e0ffba8b493001f7c4797d15a` | общая историческая основа main и AG_pather |
| `ag-ci-full-cp23-20261010` | `7396ea3fab5a61d76406e7527738182ea15d0e23` | историческая CI ветка CP23, предок AG_pather |
| `ag-ci-linux-cp24-20261010` | `bf17383c4c0f670498321e6185775e9c63a06504` | историческая CI ветка CP24, предок AG_pather; новые Linux CI не запускать |
| `ag-ci-full-cp26-20261010` | `c9139e745796a2d6f53dbd9acf62fa60e5fe90a4` | историческая CI ветка CP26, предок AG_pather |

- Compare `main...10.1`: ahead=1, behind=0. `main...10.1A/10.1B`: ahead=3, behind=0; 10.1B содержит 10.1/10.1A. Оба fast-forward по истории от main, но **не выполнены**.
- Compare `main...AG_pather`: ahead=124, behind=34, merge base `95122c90...`. Проекты разошлись до Codex 10.0B. Git tree изменений у них самостоятельные.
- `AG_pather` и три `ag-ci-*` — последняя включает их в истории; ветки CI не отдельные активные компоненты.
- Ранее file-tree comparison выявило четыре пути изменённые с обеих сторон: `.gitignore`, `docs/ROADMAP.md`, `scripts/demo.ps1`, `scripts/run-tests.ps1`. Пересечение путей **не является точным git merge conflict list**, для него нужен реальный merge-tree. Дополнения 10.1A/B не пересекаются с изменёнными AG_pather путями по прежнему сравнению, всё равно нужен rehearsal.
- В GitHub нет PR: `pulls?state=all` вернул 0.

## III. CI / пользовательская Windows приёмка

- Github Actions: всего **47** исторических runs на момент readback (включая старые). Последний AG Supervisor Windows run `38025855638` для `1b9f7385178ca23aef60fa080d0fccf57d2632b4` завершился SUCCESS; это synthetic code tests, не CP54A2 RPC transport.
- Последний main workflow ранее завершался SUCCESS, но текущий `main@b18f31c` после этого success commit; нельзя заявлять, что текущая main прошла новый CI без отдельного readback.
- На ветках `raif-10-1-*` запусков Actions не обнаружено. Документ 10.1B утверждает `PASS_STATIC_ONLY / HOST_NOT_RUN`; 20 тестовых методов объявлены, но Windows пользовательский прогон не зафиксирован.
- Для 10.1B уже подготовлены два PS1 скрипта Host QA; они не изменяют pinned ветку 10.1. Ограничения: PowerShell 5.1 не проверен на пользовательской машине; Windows Job Objects для потомков процессов не доказаны.
- Предыдущий CP42 probe RASSVET_DESKTOP показывал каталог `C:\GIT\Rassvet_AI_Fabric` присутствующим при `git_metadata_present=false` и `git_on_path=false`. Состояние могло измениться; перед clone/merge повторно прочесть локальную директорию. Нельзя удалять её автоматически.

## IV. Issues и архитектурные разногласия

- Issue #1: QA конфликт `tests/test_windows_vault.py` исправлен на AG_pather через переименование `tests/test_supervisor_windows_vault.py`, также обработка codepage/Python alias; отдельный Windows CI PASS. Issue остаётся OPEN до merge rehearsal и комбинированной Windows регрессии.
- Issue #2: RFC о hot-switch/loopback имеет status APPROVED FOR IMPLEMENTATION внутри `design/RFC_ACCOUNT_SWITCH_MECHANICS.md` (изменённая директива). Но фактические CP53 переключения = 0 и Native RPC вызывается = 0. Скорости «1.8 s / <100ms» и non-stop SSE остаются гипотезами до runtime evidence.
- Issue #3: координация merge, указывает на 10.1 как FF-кандидата. Теперь существует более новая накопительная 10.1B ветка `a5c4e6d...`; требуется приёмка и явный выбор политики включения в main.
- `docs/PRODUCT_SCOPE.md` в AG_pather изменён под автоматическую ротацию, но `docs/ROADMAP.md` всё ещё содержит одновременно новое требование ротации и старое «Явный отказ от автоматической ротации потребительских Google-аккаунтов» — противоречие спецификации. Актуальные внешние условия провайдера не меняются от изменения внутренних docs.
- `design/RAiF_AG_Supervisor_Master_Implementation_Plan_CP54.md` описывает read-only/native capability gates и не должен считаться свидетельством working proxy. Нет AG-tools runtime dependency.

## V. Итоговая интерпретация

Это **один репозиторий с двумя активными потоками разработки**, а не два готовых продукта, требующих немедленного слияния:
1. Core Fabric: 10.0B закончен → 10.1/10.1A/10.1B опубликованы **как подготовка офлайн host QA**, но не Windows-accepted и не в main.
2. AG Supervisor: own Vault+Pool существуют → 54A1 synthetic RPC observer CI PASS → 54A2 Windows observer ran, no listener found so **RPC untested**.
3. Merge QA, issue #1 и нормализация документации требуются до общей ветки. Чужие RFC-обещания не равны verifiable acceptance.

## VI. Следующие курсоры

**Core Fabric:** `RAI-FABRIC/10.1B-WINDOWS_HOST_ACCEPTANCE` → автономная host QA на точно pinned 10.1 checkout → `10.1C-ADVERSARIAL_OFFLINE_REVIEW` → отдельный согласованный merge rehearsal → решение о merge; не запускать Codex live turn повторно.

**Antigravity:** `AG_pather/CP-54A2_RPC_PORT_DISCOVERY_INCONCLUSIVE` → `CP-54A3_NATIVE_TRANSPORT_FORENSICS_READONLY` → `G1_APPROVED_SESSION_INTERFACE` → `CP-54B_QUOTA_AND_AUTH_OBSERVER`; не трогать native session/бинарники.

**Integration:** `ISSUE-3_MERGE_REHEARSAL_DETACHED_ONLY` после host-acceptance, не force push, не изменять main без явного разрешения пользователя.

**Контракт:** Windows-only, PowerShell 7 для нового AG тестового контура, JSONL всех стадий, минимум локальных прогонов и GitHub CI, никакого исполнения бинарников или токенов в Actions.
