# Codex App Server — корректировка `thread/start` (09.9-C)

**Дата:** 2026-10-10. **Состояние:** локальные тесты PASS, Windows-host retest ожидается. **Платные вызовы:** нет.

## Основание

Получен архив с пользовательской машины `RAiF-Windows-RESULT-CODEX-THREAD-20261010_055500_900cc597.zip` (SHA-256 `21bdbc542898f7164fcba86d9efa03ab8cfb1c93f0831ba0c1536178d1a3868b`). CRC ZIP корректен. `initialize` подтверждён, `initialized` отправлено, но `thread/start` завершился `RPC_ERROR_FROM_SERVER`. `turn/start` не отправлялся, дочерний процесс остановлен.

Анализ исходного кода выявил конкретный дефект контракта: `thread/start` получал `sandbox: "readOnly"`, хотя wire-формат `SandboxMode` требует `read-only | workspace-write | danger-full-access`. Не следует путать wire-режим thread/start с объектом `SandboxPolicy` `type=readOnly` для turn/start. Отдельно офлайн-протокол применял недействительное `approvalPolicy=unlessTrusted`; заменено на `on-request`. Оба старых значения поддерживались фальшсервером и потому не выявлялись прежним тестом.

Источники контрактов:
- https://github.com/openai/codex/blob/main/sdk/typescript/src/threadOptions.ts
- https://github.com/openai/codex-plugin-cc/blob/main/plugins/codex/scripts/lib/codex.mjs
- https://github.com/openai/codex/issues/25569

## Исправление

1. Реальный транспорт: `sandbox=read-only` при `thread/start`; `model=null`, `approvalPolicy=never`, `ephemeral=true` сохранены, `turn/start` отсутствует.
2. Имитатор теперь требует корректное wire-значение `read-only` и отклоняет устаревшее `readOnly`.
3. Добавлен отрицательный тест RPC-ошибки на этапе `thread/start` с секретоподобным текстом. В отчёт передаётся только ограниченный целочисленный `rpc_error_code`, поле `error.message`/`error.data` не сохраняется.
4. Офлайн-протокол: `sandbox=read-only`, `approvalPolicy=on-request`.
5. Исправленная пара для Windows: `RAiF-Codex-Thread-09_9C.zip` + `Start-RAiF-Codex-Thread-09_9C.ps1`; ZIP закреплён в PS1 по SHA-256. Результат — в корне `C:\GIT\Rassvet_AI_Fabric`.

## Ограничения

Неверный enum — **подтверждённый дефект запроса**, но первичный серверный `error.code` в старом архиве не сохранён. До повторной проверки на машине пользователя нельзя утверждать, что это единственная причина BLOCKED. Пустой отдельный `CODEX_HOME` может накладывать независимые ограничения на создание потока. При новой ошибке анализировать только число `rpc_error_code`, статус и этап; реальные токены и сообщения не выгружать.

Выполнять только на Windows через `pwsh` 7. Не менять оригинальный Codex HOME, `.codex`, BPR40, CONTROL TOWER и Antigravity. Не запускать модели, OAuth или платный API. Один Windows CI на кодовый коммит; дополнительные проверки на личном хосте через один ZIP+PS1.

**Следующий курсор:** `RAI-FABRIC/09.9-D-HOST_THREAD_START_RETEST`.
