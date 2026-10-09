# Протокол проверок — R5, 10 октября 2026 года

**Статус:** проверка версии `RAI-FABRIC/09.2` завершена в локальной Linux-среде и на GitHub-hosted Windows.

| Этап | GitHub Actions | Python 3.11 | Python 3.13 |
|---|---|---|---|
| 08.3 | [37999273894](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/37999273894) | PASS | PASS |
| 09.0 | [37999596507](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/37999596507) | PASS | PASS |
| 09.1 | [37999863741](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/37999863741) | PASS | PASS |
| 09.2 | [38000162444](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38000162444) | PASS, 81 тест | PASS, 81 тест |

В последнем прогоне дополнительно прошли оба PowerShell-сценария: обычная `mock`-задача и `codex-mock` с отдельным дочерним процессом. Каждый создаёт только собственную тестовую БД в TEMP.

**Не проверено:** личный Windows-хост и RTX 5070 Ti, OAuth/PKCE, подписная квота, настоящий Codex App Server, самостоятельная среда Antigravity, BPR40 публикация в три башни. Эти операции не являются частью тестов, их нельзя считать готовыми.

Следующий этап: `RAI-FABRIC/09.3-SIWC_OAUTH_READINESS_AND_CONSENT_GATE`.
