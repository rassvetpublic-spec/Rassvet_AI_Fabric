# RAiF W0B — сохранение 134 файлов WIP; W1 готов только к запуску

Дата 2026-10-10. Репозиторий `rassvetpublic-spec/Rassvet_AI_Fabric`, проектный курсор `AG_pather`. База: `4ec41fdcb70cdbc1b00c48001bd0a1b6c57d6aca`. Это readback + операционный handoff, не host PASS.

## Установленные факты W0B
- Пользовательский RESULT `RAiF-W0B-RESULT_20261010_132403_5fe9045c.zip`, SHA-256 `fb5b8f954f67dd840bf2ee67524cbe365162d90a90cafaae560b311a921a509d`: ZIP CRC PASS, пять allowlisted файлов. `STEPS.jsonl` — 5 PASS + 1 BLOCKED, финал `PARTIAL/PRESERVE_DIRTY_WORKTREE`.
- Точный Git SHA `78211c7ed73988da93a6d8a33d47ec6187f464d7ea2a9a00c182bbd7a1ecf30f` повторно подтверждён в пользовательском отчёте, origin ожидаемый. HEAD до/после `b18f31cb39bd655c7fd7e50466069f23d29c957a`, `refs/remotes/origin/main` в локальном клоне тоже старый.
- **134 tracked modified, 0 staged/untracked/deleted/conflicts/renames; это WIP, сохранять.** Локального commit object main 10.3 нет либо он нечитаем (`MISSING_OR_UNREADABLE`). 7 Git-read-only вызовов, 0 сетевых операций, 0 мутаций согласно RESULT.
- Старый `C:\GIT\Rassvet_AI_Fabric` не источник W1. Не делать blind pull/reset/clean/stash/rebase/checkout, не создавать связанный worktree из его `.git`.
- Main 10.3 на GitHub `8dc6ee32eabd3334012763bac8e641f682e478c6`, tree `8d2a0d0c195a3ffbb64cf26ba46e906936261894`; точная проверка дерева через GitHub: 289 обычных файлов, 0 symlinks/gitlinks/.gitattributes/.gitmodules. CI on PR HEAD 428/428 PASS, но W1 **ещё не выполнялся на пользовательском Windows**.

## Новая укрупнённая W1 (одно действие вместо микроволн)

Собраны `RAiF-W1-Fabric10_3-R1.zip` SHA-256 `b29a6739415af767d346fae802d8eea684b2b7a9a68881f7e3039e93ef32ff15` и `Start-RAiF-W1-R1.ps1` SHA-256 `2d3d734d2c177857fd58727f0b92261f27d107d8ed99e6a070aff9131607a0d9`. ZIP CRC PASS, четыре точных члена, все payload SHA256 подтверждены. Код Python-harness проверен **36/36 независимых чистых офлайн-тестов на Linux**; это тесты механики gate, **не** подтверждение PowerShell/Windows. Windows PS7 AST/пользовательский прогон: NOT_RUN.

**Запуск является явным разрешением на одну публичную HTTPS GitHub-копию в НОВОМ каталоге D:**
`pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "D:\ЗАГРУЗКИ\Start-RAiF-W1-R1.ps1" -Apply`.

Поведение:
1. Проверить exact ZIP hash/allowlist/payload, Python >=3.11, неизменный W0 git.exe.
2. `git clone --no-checkout --depth 1 --single-branch --branch main` **только** в новый `D:\ЗАГРУЗКИ\RAIF_W1_RUNTIME_<id>\isolated_source`. Branch head drift, неправильный origin/tree, symlink/gitlink/filter attribute/path ⇒ STOP до checkout. Никакой команды в `C:\GIT`.
3. Только после full-tree verification: isolated detached checkout exact 10.3. Один запуск полной Windows unittest suite (ожидается 428/428, включая 20 worktree-review в том же запуске, без 20 повторных тестов). Новые отдельные SQLite DB и mock + codex-mock workflows.
4. После тестов повторный SHA/HEAD, отсутствие dirty/ignored, один обезличенный RESULT ZIP `RAiF-W1-RESULT_<runid>.zip` (5 файлов), runtime только D:.

**Сила результата:** даже W1 PASS означает `WINDOWS_ISOLATED_10_3_CORE_ACCEPTED` для offline core + mocks, а не live OAuth, streaming, AG account identity, permission to merge, provider access или powerloss durability. Без network OS firewall isolation; дочерний test process имеет изолированные environment/TEMP/HOME, но не аттестовано как network-disconnected. Timeout ⇒ fail closed и host inspection. Python security extras на машине не устанавливаются автоматически.

Если `-Apply` не задан, launcher делает только inspection package/toolchain, без git clone или tests. Если main изменился с `8dc6ee32...`, текущий пакет безопасно откажет — **не** будет молча тестировать другой commit.

## -- / == / ++ / ~~

- **--:** Blocker был не отсутствие Git, а 134 модифицированных tracked WIP + отсутствие exact 10.3 object. Их не следует «лечить» reset/pull.
- **==:** Изолированное ветвление в новый D:-checkout с фиксированным Git SHA, tree SHA, 289 modes/path gate, Python unittest + mocks и итоговый readback; 36/36 helper tests PASS, host NOT_RUN.
- **++:** При W1 PASS запускать W2 / 10.4 CP54D durable recovery: crash, cancellation, leaked subprocess, lost ACK, double-effect fail-closed; один источник/тесты/CI, один результат.
- **~~:** Шесть волн мастер-плана остаются, но W0 CLOSED AS TRIAGE, а W1 запущен как independent source staging. G2 и Tower BPR5 R8 остаются параллельными закрытыми для мутаций воротами.

**Next cursor:** `W1/ISOLATED_MAIN_10_3_WINDOWS_HOST_ACCEPTANCE`. Scope: NO_MAIN_MERGE, NO_TOWER_AUTHORITY_CHANGE, NO_ACCOUNT_SWITCH; original C: WIP preserved.
