# RAiF W1-R2 — независимое закрытие офлайн-ядра Fabric 10.3

**Дата:** 2026-10-10. **Владелец:** \`rassvetpublic-spec/Rassvet_AI_Fabric\`, проектная ветка \`AG_pather\`. Следует за \`s08_raif_w1_428_pass_mock_contract_resume_20261010_r1.json\`.

## 1. Две оригинальные Windows-квитанции проверены вместе

- Исходный \`RAiF-W1-RESULT_20261010_134700_872266a9.zip\`, SHA-256 \`61535dd5ec1622d985e9ded2c321a21f0191c742dcf5ae77fa8b0bb4fb5d795a\`: ZIP CRC PASS; \`UNITTEST/PASS/EXACT_428_WITH_WORKTREE_20\` и \`report.json.unit_tests=PASS\`, 428/428, 20 worktree-тестов, skipped=0. Остановлен только ошибочным полем \`task_id\` в W1 host harness.
- Новый \`RAiF-W1R2-RESULT_20261010_140155_51222991.zip\`, SHA-256 \`500b99cc558a4fe10a2dcfcd04b34a51e544e95281c4c3e1d344992ccc29031c\`: ZIP CRC PASS, строгий allowlist 5/5, 9/9 стадий \`PASS\`. \`PRIOR_W1\` проверяет точный SHA старого результата, не повторяет 428.
- \`SOURCE/PASS\` + \`POSTCHECK/PASS\`: exact commit \`8dc6ee32eabd3334012763bac8e641f682e478c6\`, tree \`8d2a0d0c195a3ffbb64cf26ba46e906936261894\`, checkout чистый после двух новых mock.
- \`QUEUE_MOCK/PASS\`: корректная проверка реального поля \`id\` в Fabric task view; \`CODEX_MOCK/PASS\`: stdio mock завершился. Сценарии сохраняют \`simulation\`, real_model_calls=0. Повторного \`git clone\` не было, исходный \`C:\GIT\Rassvet_AI_Fabric\` не использовался.
- Итог \`W1_OFFLINE_CORE_ACCEPTED_COMPOSITE\` / \`PASS_COMPOSITE_OFFLINE_CORE_ONLY\`. Две отдельные Windows-квитанции логически связаны по exact исходнику и SHA архива, а не задним числом превращены в один прогон.

**Не заявлено:** реальный OAuth, Antigravity identity/hot-switch, реальное переподключение потока, power-loss durability, restart с неизвестными внешними side effects, разрешение на merge или запись в Башню. SHA-256 является контролем целостности, но не цифровой подписью или внешним attestation.

## 2. [--] Критическая проверка пути к W2

Исследованы исходники \`src/rai_fabric/store.py\` и \`src/rai_fabric/worker.py\` в двух состояниях. **Интегрированный main 10.3 отличается от AG_pather**: в \`main\` уже включён \`codex-mock\`/транспорт Codex и актуальные Core-тесты; \`AG_pather\` хранит отдельную историю Supervisor/continuity. Не писать Fabric 10.4 поверх устаревшей основы \`AG_pather\`, не делать blind cherry-pick, не изменять \`main\` напрямую.

В \`main\` \`FabricStore.recover()\` при истёкшей аренде уже делает \`BLOCKED\` и \`VERIFY_EXTERNAL_SIDE_EFFECTS\`, а \`BEGIN IMMEDIATE\` защищает локальные SQLite транзакции. Но пока **нет target-scoped durable effect-idempotency ledger** и независимого доказательства, что внешний эффект не выполняется повторно после lost ACK. \`continuity.py\` Supervisor — отдельный прототип, не доказанная интеграция в основной TaskGraph. Не выдавать название CAS/ledger за гарантию внешнего эффекта.

## 3. [==] Решение

W2 реализовывать **от pinned \`main@8dc6ee32...\` в отдельной кандидатной ветке** после сверки HEAD, не через merge/force. Контракт и тесты определить в \`design/d02_raif_10_4_durable_recovery_w2_20261010_r1.md\`. Один крупный source+tests набор → один Windows CI на изменённый код → один независимый Windows host RESULT. Ни реальный провайдер, ни пользовательский исходный checkout для испытаний не нужны.

## 4. [++] Курсоры

- **W1:** \`F1_ACCEPTED / WINDOWS_ISOLATED_10_3_OFFLINE_CORE\`.
- **W2:** \`W2/10_4_DURABLE_RECOVERY_EXACT_MAIN_BASELINE_IMPLEMENTATION_PLAN\`.
- **W3:** \`10_5_EXECUTOR_MANUAL_AG_HANDOFF\` только после W2-приёмки.
- **AG/G2:** CLOSED; Tower BPR5 — candidate, not sealed.
- **Merge:** отдельный owner MTD для конкретного PR/SHA и независимый QA. Из W1 не наследуется полномочие на merge.

## 5. Изоляция

\`C:\GIT\Rassvet_AI_Fabric\` содержит 134 изменённых tracked-файла, их нельзя стирать. Runtime/RESULT только \`D:\ЗАГРУЗКИ\`. Действующая Tower authority — GDrive CONTROL_TOWER, GitHub Tower — реплика (\`production_sync=false\`). Никаких изменений в них из W2.
