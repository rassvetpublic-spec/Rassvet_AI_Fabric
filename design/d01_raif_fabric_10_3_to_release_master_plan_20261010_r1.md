# RAiF — укрупнённый MASTER EXECUTION PLAN после 10.3 (R1)

**Дата:** 2026-10-10. **Владелец инженерного плана:** Rassvet_AI_Fabric, ветка AG_pather. **Режим:** BPR Improver (-- / == / ++ / ~~), WINDOWS-ONLY, evidence-driven. **Это проектный план, а не изменение authority или решение о merge.**

## 0. Главное решение

**Перестать повторять уже пройденные CP-этапы.** Сначала довести уже объединённый Fabric 10.3 до безопасной повторяемой эксплуатации на одном реальном Windows-хосте, затем обеспечить реальное восстановление задач, затем интегрировать разрешённые рабочие каналы и пять проектных доменов. Antigravity Supervisor/реальная identity идут как отдельная gated дорожка; неподдерживаемый live-switch не должен остановить выпуск полезного Fabric Core.

**Стратегическая цель не изменена:** независимая Windows-first среда разработки KAT9I_OS, CKS, RULESHUB, ANTIGRAVITYDATA и CONTROL_TOWER с provenance, конкретным Git SHA, задачами и арендой, безопасным продолжением после сбоев, измеримыми квотами и минимальными облачными расходами. Не создавать конкурирующую Башню/CKS/SSOT. Три Башни — развивающиеся проекции и контуры с разграниченными полномочиями, не замороженный «вечный канон».

**Укрупнение:** один рабочий пакет на волну, один собранный source+tests commit и один стандартный Windows CI на реально изменившийся код; один общий Windows ZIP+PS1 и один RESULT при необходимости host evidence. Одна точка handoff, а не checkpoint после каждого микротеста. Docs-only commit не запускает CI.

## 1. Доказанная база (точные источники, не повторять)

| Контур | Источник / SHA | Проверенный результат |
|---|---|---|
| Fabric main 10.3 | 8dc6ee32eabd3334012763bac8e641f682e478c6 | PR #4 merged, tree 8d2a0d0c195a3ffbb64cf26ba46e906936261894 совпадает с exact PR HEAD tree; Windows PR CI #38049455516 428/428 PASS, main push run #38049976872 SUCCESS |
| AG_pather перед этим планом | 7dc61a2c67c5d4553ca57d39e25b8153a1c5fe14 | BIGWAVE 02 код в 975c61a5b77ca69a674df994fbcab0d372c62ac9, Windows CI #38051697374 265/265 PASS; 28 новых тестов |
| BIGWAVE 02 пользовательский Windows RESULT | RAiF-BIGWAVE02-RESULT_20261010_123437_e29e2e6a.zip | SHA-256 32919eb281db90c5462c98723c7b94348935b66545bd0167adce5fa706700634; ZIP CRC PASS, пять отчётных файлов, 28/28 PASS, 0 errors/failures/skips |
| Fabric host из RESULT | RAIF_FABRIC_HOST_DIAGNOSTIC_10_3/1 | PARTIAL; verdict GIT_EXECUTABLE_MISSING, stage GIT, git_reads=0, source_class UNKNOWN, host_qa_verified=false |
| CP54C1/CP54D | BIGWAVE R1/R2 | Synthetic rollback/continuity PASS. Реальное восстановление сессии и crash-powerloss не подтверждены |
| Tower | Drive folder ID 1d3boKYmIGgOqLEZB3nlHTt-sTl8i9QnW | Действующая authority по решению пользователя; GitHub CONTROL_TOWER только реплика, production_sync=false, merge_requires=MTD |
| BPR40/BPR5 | Router v18 / BPR40 v4.0.3 RELEASED; Tower Issue #30 | BPR5 CANDIDATE_HARDENED_IN_FLIGHT, NOT SEALED; не является новой authority и не включён как действующий Router |
| Account identity | G2 | CLOSED / UNVERIFIED; ноль разрешённых живых переключений этим планом |

**Критическое различие:** hosted Windows CI PASS, синтетический Windows результат и read-only Git preflight — три разных уровня. Ни 428/428, ни 265/265 сами по себе не подтверждают работоспособность конкретного каталога C:\GIT\Rassvet_AI_Fabric на пользовательском Windows.

## 2. Непосредственная причина блокировки

В отчёте BIGWAVE 02 диагностический Python искал Git через shutil.which("git.exe") и **не нашёл его в PATH дочернего процесса**. Ветка проверки остановилась до любой Git-команды (git_reads=0). Вывод **НЕ** означает, что Git не установлен и **НЕ** означает, что клон повреждён. Не перезапускать 28 синтетических тестов только из-за этого.

**Гипотезы, не доказательства:** Git установлен в стандартном Windows-каталоге вне PATH; алиас/окружение PowerShell отличается от Python; установлена portable-сборка; Git вообще отсутствует. Разрешены только read-only проверки.

## 3. Critical path: шесть крупных волн

### W0 / TOOLCHAIN DISCOVERY + ONE HOST PREFLIGHT — ближайшее действие

**Цель:** точно установить, где находится пригодный git.exe и какое состояние существующего клона, не изменяя машину.

**Действия:** один локальный PowerShell 7 launcher в D:\ЗАГРУЗКИ: системные Get-Command/where и список фиксированных доверенных вариантов вроде C:\Program Files\Git\cmd\git.exe, C:\Program Files\Git\bin\git.exe, C:\Program Files (x86)\Git\cmd\git.exe, %LOCALAPPDATA%\Programs\Git\cmd\git.exe; проверить абсолютный путь, отсутствие junction/reparse, тип файла и bounded --version. Никакой автоматической установки, записи системного PATH или доверия к неизвестному бинарнику. При найденном экземпляре использовать *абсолютный путь*, либо изменить только PATH текущего дочернего процесса.

Далее только если Git подтверждён: проверить ровно существующий C:\GIT\Rassvet_AI_Fabric (его .git/config, root/origin, HEAD, clean status, ignored, повторный HEAD readback). Команды не делают fetch/clone/pull/reset/checkout, не требуют credentials, не запускают код из исследуемого клона. Если клон отсутствует/не Git/грязный/не тот SHA — только фиксированный BLOCKED с причиной. Не исправлять пользовательский checkout автоматически.

**Артефакты:** один ZIP+PS1 (или только PS1, если достаточно), единственный RAiF-W0-RESULT_<runid>.zip из D:\ЗАГРУЗКИ с 5-файловым privacy-safe allowlist. Не повторять 28/28 без изменения тестов.

**PASS (F0):** Git executable найден/байтово зафиксирован и clone классифицирован до конкретного SHA; нулевые внешние запросы и мутации. При отсутствии Git: честный GIT_NOT_DISCOVERABLE, пользовательское решение об установке, без автоматического скачивания. При fail-closed — переход на W0.RECONCILE, а не попытка repair.

### W1 / FABRIC 10.3 POST-MERGE WINDOWS HOST ACCEPTANCE

**Зависимость:** F0 PASS и допустимое состояние источника/точного commit pin. Не перетирать пользовательский C:\GIT.

**Действия:** на точном дереве main SHA 8dc6ee32... проверить Windows preflight, targeted worktree-review (20), полный офлайн suite 10.3, SQLite lease/generation, Codex mock thread/turn, checkpoint SHA/readback и cancellation. Для тестов, требующих изменения Git, нужен отдельный уникальный D:\ЗАГРУЗКИ staging с проверенным pin, выключенными hooks/filters и **без записи в .git оригинального клона**. Не создавать staging из сомнительного источника или при скрытых symlink/submodule/filters. Не инициировать новый live Codex turn 10.0B.

**PASS (F1):** полный оригинальный host evidence при точном source tree; ожидаемое количество тестов берётся из pinned test discovery, а не суммируется вручную. Отчёт чётко различает hosted CI, host source acceptance, mock E2E и реальные model calls (0). Fail/Skip≠PASS.

### W2 / FABRIC 10.4 + CP54D DURABLE RECOVERY

**Зависимость:** F1 PASS или отдельно диагностированная изолированная тестовая среда; provider credentials не нужны.

**Действия:** эксплуатационный цикл TaskGraph/WorkspaceRegistry: lease generation, heartbeat, отмена, дерево процессов Windows Job Objects, timeout, SQLite durable effect journal, атомарный checkpoint/cursor, идемпотентность и **UNKNOWN_OUTCOME → BLOCKED_PENDING_REVIEW**. Пакет fault injection: crash-before/after checkpoint, lost ACK, stale lease, double-replay, process exit/timeout, junction ancestor, power-loss approximation, concurrent writers. Один общий source+tests commit и один Windows CI. Для реальных crash/reboot использовать отдельно разрешённую изолированную среду; никогда не прерывать текущую Antigravity/Codex работу.

**PASS (F2):** reboot/crash, повторная выдача задачи и неизвестный внешний side-effect не вызывают двойного необратимого действия; отчёт содержит exact pin, after-state и восстановимый cursor. Синтетика не называется реальным power-loss доказательством.

### W3 / FABRIC 10.5 EXECUTOR + ANTIGRAVITY MANUAL-HANDOFF

**Зависимость:** F2 и разрешённость исполнителя.

**Действия:** единый task routing для официального Codex App Server, локальных Git/PowerShell и Antigravity standalone через **read-only telemetry + user-controlled handoff**. Один task-id/cursor/provenance во всех каналах, явная отмена, ошибки 401/403 отдельны от 429, неизвестная квота не считается доступной. Не повторять успешный live Codex turn 10.0B; новая платная/подписная live операция — только отдельный пользовательский gate и ограниченный сценарий.

**PASS (F3):** одно и то же mock-задание проходит submit → claim → bounded execute → checkpoint → verify → recovery/review; provider calls=0 в безразрешительном режиме. Нативный auto-hot-swap не нужен для этого PASS.

### W4 / FABRIC 10.6 FIVE-DOMAIN READ-ONLY INTEGRATION

**Зависимость:** F3.

**Действия:** типизированные read-only интерфейсы к KAT9I_OS, CKS, RULESHUB, ANTIGRAVITYDATA и текущей GDrive CONTROL_TOWER. BPR40 Router v18/4.0.3 — только действующий readback; BPR5 — параллельный shadow-кандидат с фальсифицируемыми доказательствами, не второй промоутер/SSOT. Сопоставление project pin/authority source/revision и ссылка на evidence, без записи в CKS Canon, Tower, Router или BPR40. Нормативная развязка Issue #1/#2/#3 отдельно от запуска кода.

**PASS (F4):** пять контуров проверены отрицательными тестами прав, отсутствия источника и drift; несанкционированный write всегда BLOCKED. Никакой promotion по факту успешного чтения.

### W5 / FABRIC 10.7 OPERATOR RELEASE + INDEPENDENT QA

**Зависимость:** F4 и независимый QA.

**Действия:** один Windows release candidate, операторский runbook, cold start, clean stop, cancellation, restart/host recovery, bundle/provenance/secrets scan, минимальный статусный HUD, практический mock E2E. Отдельный PR и независимое ревью **точного SHA и дерева**; merge только с подтверждением владельца для указанного PR/SHA. Не выполнять «глобальную синхронизацию» Башен как побочный эффект релиза.

**PASS (F5):** локальная воспроизводимость, отсутствие credential leak, точные исполняемые байты и статус каждого внешнего канала, восстановление без слепого replay; после owner gate — ограниченный merge/release. Unsupported возможности честно маркируются.

## 4. Параллельная gated линия AG / CP54B3–CP54C

Собственный RAiF Vault уже имеет девять защищённых записей, но **наличие записей ≠ действительная авторизация Standalone**. AG-tools исключён из runtime.

**AG0:** только локальный read-only наблюдатель, независимая привязка identity к opaque handle и permission review. Нынешний G2 CLOSED. Даже живой GetUserStatus может инициировать downstream request; для него нужна отдельная explicit approval, заранее проверенный LS PID+FILETIME и фиксированный обезличенный отчёт.

**AG1:** CP54C1 synthetic rollback harness уже принят. Реальный переключатель не разрабатывать как утверждённый способ, пока не доказана допустимая операция refresh/reload/handoff, независимая identity и восстановление исходной сессии. Если официально подходящего интерфейса нет — MANUAL_HANDOFF_ONLY + TaskCheckpoint (F3), без блокировки Core.

**AG2:** только после отдельного разрешения: проба 2 профилей с фактическим возвратом к исходному; при G3 PASS — условно до 5 включая исходный за 60 секунд, с аварийным rollback priority. Child respawn≠hot-swap; новое stream request≠продолжение прежнего SSE. Никаких автоматических обходов quota или bearer replay вне разрешённого интерфейса.

AG, BPR5 и пять доменов — отдельные плечи разработки. Их OPEN gates не должны менять исторические PASS или автоматически менять Core Release gate.

## 5. Исполнимый механизм Improver / анти-SSOT Sprawl

Для каждой **крупной волны**, а не каждого микрошага:
- **[--] Backward:** опровергнуть самое слабое доказательство предыдущего шага, проверить real source SHA, false PASS, race, неизвестную причину.
- **[==] Present:** минимально реализовать нужное, только с проверяемыми тестами и обезличенным evidence; one owner per effect/target.
- **[++ ] Lookahead:** подготовить следующий interface/test/gate; не исполнять live side effects заранее.
- **[~~] Re-plan:** изменять детализацию при новых фактах, но не менять цель, authority, privacy, host-only и право на merge без отдельного решения.

Пример сегодняшнего --: «GIT_EXECUTABLE_MISSING» — проблема обнаружения инструмента, не доказанный дефект клона. Не делать новый clone/merge или 428-test run, пока Git и exact source не классифицированы.

**Проектный checkpoint является владельцем оперативного курсора.** Tower принимает только ссылку или производную проекцию и не зеркалирует изменчивые курсоры как новый SSOT. GitHub CONTROL_TOWER production_sync=false; PR #28/#29 и BPR5 Issue #30 имеют самостоятельные gates.

## 6. Stop/Go; ресурсы и границы

**Всегда STOP:** источник/HEAD не тот, Git clone грязный, unknown credential authority, неизвестный side effect, утечка секрета, unsupported provider interface, несовместимый target revision, отсутствующее MTD на изменяющую операцию. Не делать reset/pull/clone поверх C:\GIT\Rassvet_AI_Fabric; не включать GitHub Linux/macOS runners, не запускать ручную CI при docs-only.

**Регламент затрат:** один Windows CI для одного законченного source+tests набора; 1 host RESULT на одну крупную волну; ручная подписная model operation только с отдельным допуском. Runtime, TEMP, отчёты и упаковка — D:\ЗАГРУЗКИ; тестовые source checkout только в уникальном изолированном staging с явным разрешением, а не внутри оригинального клона.

**PR #4 аудит:** merge реально выполнил пользовательский GitHub account; PR body и проектный checkpoint ограничивали MTD 011011 staging/PR. Отдельное подтверждение конкретного merge/SHA в GitHub не найдено. Вердикт MERGE_EXECUTED / AUTHORITY_EVIDENCE_UNVERIFIED (не автоматически UNAUTHORIZED). Уточнение owner evidence — отдельная документационная задача, не причина остановить W0 read-only.

## 7. Следующие точные курсоры

- **СЕЙЧАС:** BIGWAVE_03 / W0_GIT_EXECUTABLE_DISCOVERY_AND_EXISTING_CLONE_READONLY_PREFLIGHT.
- **Затем при F0 PASS:** RAI_FABRIC / 10.3_POST_MERGE_WINDOWS_HOST_ACCEPTANCE, затем 10.4_DURABLE_TASK_RECOVERY.
- **AG:** CP54B3 / G2_IDENTITY_READ_GATE_CLOSED (отдельное решение).
- **Tower/BPR5:** BPR5_R8 / EXTERNAL_AUTHORITY_REAL_TARGET_GATE; без promotion.
- **Merge:** отдельный PR, независимый QA, owner MTD на точный SHA. Без blind merge AG_pather в main.

**Следующий артефакт исполнителя:** не новая серия микропакетов, а один bounded offline W0 launcher + redacted RESULT. Уже принятые BIGWAVE 28/28, AG 265/265, Main PR 428/428 и Codex turn 10.0B **не повторять**.
