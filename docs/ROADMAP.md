# Roadmap and acceptance gates

## R0.1 — Original local core (this package)
- [x] Explicit isolated initialization
- [x] SQLite task queue/dependency, exclusive claim, leases, heartbeat, fencing generation
- [x] Durable checkpoint with stage, cursor, sha256 and readback
- [x] Crash recovery: BLOCKED for reconciliation, no blind relaunch
- [x] MCP stdio read-only tools (legacy handshake)
- [x] PowerShell demo and unit tests
- [ ] Native Windows validation on the actual host
- [ ] Antigravity real login/inference (not tested, user action required)

## R0.2 — Provider adapters
- [ ] Codex App Server JSON-RPC, clientInfo, thread/start, turn/start, delta + turn/completed
- [ ] Explicit ChatGPT plan OAuth (SIWC, PKCE, token refresh, Windows credential storage)
- [ ] Event/approval/cancel handling; no API-key fallback
- [ ] Antigravity safe Windows launcher (avoid .cmd argument injection), resume by conversation_id
- [ ] Verified Windows process supervision (Job Objects) and cancellation/timeout tests
- [ ] Per-provider usage records: input/output/cache, no fake money estimates

## R0.3 — Local GPU and budget-aware dispatcher
- [ ] Ollama or llama.cpp local model selection, 5070 Ti VRAM preflight, latency/quality benchmark
- [ ] Local embeddings/RAG, prompt shaping, context byte caps and retry budgets
- [ ] No billable API fallback unless operator explicitly enables it

## R0.4 — BPR40 and remote chat connectivity
- [ ] Verify current Router authority, publication schemas and allowed mutations
- [ ] Read-only BPR40 bridge, then independently approved tri-tower checkpoint publication
- [ ] Signed receipts, independent review, metadata-only sharing with cloud agents
- [ ] Secure MCP tunnel/authorized user consent for ChatGPT Web; no scraping private endpoints

## R0.5 — Long-running production controller
- [ ] Persistent daemon/service on Windows, queue polling and explicit scheduling
- [ ] Worktrees/conflict locks, artifact diffs, integration QA and rollback
- [ ] Crash/reboot recovery tests, watchdog and UI with current cursor/status

## Distinguish done vs planned

The code in R0.1 only implements the checked items. The remaining rows must not be described as working. Avoid using the word "autonomous" until native cancellation, crash recovery, and provider integration have passed acceptance tests.
