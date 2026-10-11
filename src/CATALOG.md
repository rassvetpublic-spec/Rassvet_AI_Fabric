# Реестр скриптов src/ (Script Registry)
> *Этот файл генерируется автоматически скриптом `scripts/generate_catalog.py`*

## Оформленные скрипты

| Имя файла | Тип | Описание |
|---|---|---|
| `rai_fabric/__init__.py` | Python | Rassvet AI Fabric: независимый прототип системы оркестрации. |
| `rai_fabric/__main__.py` | Python | Модуль __main__ |
| `rai_fabric/cli.py` | Python | Явное локальное управление: задания и токены не отправляются в API без согласия. |
| `rai_fabric/codex_live_executor.py` | Python | Один разрешённый Codex App Server turn -> один файл -> локальный unittest. |
| `rai_fabric/codex_mock_server.py` | Python | Подставной процесс App Server для офлайн-интеграционных тестов. |
| `rai_fabric/codex_mock_transport.py` | Python | Офлайн-stdio транспорт к подставному процессу Codex App Server. |
| `rai_fabric/codex_protocol.py` | Python | Офлайн-контракт обмена с Codex App Server: не запускает процессы и модели. |
| `rai_fabric/codex_real_transport.py` | Python | Управляемый App Server: только initialize и необязательный thread/start. |
| `rai_fabric/credential_store.py` | Python | Атомарное хранение проверенной OAuth-сессии под DPAPI текущего Windows SID. |
| `rai_fabric/gateway.py` | Python | Локальный шлюз инструментов только для чтения, без произвольных shell-команд. |
| `rai_fabric/host_gate_10_1b.py` | Python | Read-only Windows host preflight for Fabric 10.1B pinned-source acceptance. |
| `rai_fabric/mcp_server.py` | Python | MCP-сервер по stdio: только чтение, согласование протокола 2025-11-25. |
| `rai_fabric/oauth_exchange.py` | Python | Офлайн-контракт OAuth code exchange и refresh для подписного ChatGPT. |
| `rai_fabric/oauth_identity.py` | Python | Проверка OpenID Connect ID-токена на доверенных JWKS без сетевых запросов. |
| `rai_fabric/oauth_readiness.py` | Python | Подготовка авторизации ChatGPT по подписке без сети и доступа к секретам. |
| `rai_fabric/store.py` | Python | Транзакционное состояние задач; не использует код OMX или Superpowers. |
| `rai_fabric/trusted_jwks.py` | Python | Доверенное получение ключей OpenAI по OIDC Discovery с fail-closed кешем. |
| `rai_fabric/windows_acl.py` | Python | Windows DACL текущего пользователя и проверка reparse points для vault. |
| `rai_fabric/windows_vault.py` | Python | Заготовка защищённого Windows-хранилища: текущий пользователь DPAPI. |
| `rai_fabric/worker.py` | Python | Явно включаемые исполнители, без веб-скрейпинга и платного API fallback. |
| `rai_fabric/worktree_review.py` | Python | RAiF 10.1: Windows-only, offline, fail-closed Git worktree diff review. |
| `raif_ag_supervisor/__init__.py` | Python | RAiF AG Supervisor: standalone-safe orchestration primitives (prototype). |
| `raif_ag_supervisor/__main__.py` | Python | Minimal non-destructive command line interface for RAiF AG Supervisor. |
| `raif_ag_supervisor/accounts_cli.py` | Python | Windows-only local account vault operations with privacy-safe output. |
| `raif_ag_supervisor/audit.py` | Python | CP-54C1/54D strict redact-by-construction stage audit. |
| `raif_ag_supervisor/continuity.py` | Python | CP-54D: offline checkpoint integrity and non-replaying resume planner. |
| `raif_ag_supervisor/core.py` | Python | Dependency-free, testable core. No credentials, no binary patches, no network. |
| `raif_ag_supervisor/diagnostics.py` | Python | Read-only diagnostic summary for Antigravity Standalone on Windows. |
| `raif_ag_supervisor/filelock.py` | Python | Advisory exclusive file locking for registry mutation. |
| `raif_ag_supervisor/identity_observer.py` | Python | CP-54B3: bounded, opt-in, local-only active-session evidence observer. |
| `raif_ag_supervisor/importer.py` | Python | Pure validation of exported account manifests. Does not persist credentials. |
| `raif_ag_supervisor/native_rpc.py` | Python | Minimal read-only observer for a running Antigravity Language Server. |
| `raif_ag_supervisor/pool.py` | Python | Quota-aware account-pool planner for Windows Antigravity Standalone. |
| `raif_ag_supervisor/quota_adapter.py` | Python | Strict, read-only parser for the Antigravity quota summary response shape. |
| `raif_ag_supervisor/quota_observer.py` | Python | Sanitized observations from the internal Standalone HTTPS quota RPC. |
| `raif_ag_supervisor/registry.py` | Python | Crash-recoverable registry of opaque account IDs, without credentials. |
| `raif_ag_supervisor/rollback_harness.py` | Python | CP-54C1 offline-only rollback fault harness. |
| `raif_ag_supervisor/session_evidence.py` | Python | CP-54C1: non-identifying process evidence for offline planning. |
| `raif_ag_supervisor/session_probe.py` | Python | Read-only Windows process discovery. No process modification or token access. |
| `raif_ag_supervisor/transaction.py` | Python | Transactional import into a user-controlled credential vault. |
| `raif_ag_supervisor/vault.py` | Python | Vault abstraction: no secrets in checkpoints, logs or account registry. |
| `raif_ag_supervisor/verification.py` | Python | Evidence-based acceptance gate for live Standalone account switching. |
| `raif_ag_supervisor/windows_vault.py` | Python | Windows Credential Manager adapter for RAiF-owned generic credentials. |
