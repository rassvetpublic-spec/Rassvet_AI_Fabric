# Протокол испытаний — R4, 10 октября 2026 года

**Официальный язык:** русский. **Статус:** локальная интеграция `codex-mock` проверена, Windows CI этой редакции ожидает публикации.

| Этап | Проверка | Результат |
|---|---|---|
| 08.3 | Windows preflight и mock-сценарий Python 3.11/3.13 | GitHub Actions `37999273894`: SUCCESS |
| 09.0 | Офлайн-протокол App Server Python 3.11/3.13 | GitHub Actions `37999596507`: SUCCESS |
| 09.1 | Реальный stdio с подставным процессом Python 3.11/3.13 | GitHub Actions `37999863741`: SUCCESS |
| 09.2 | SQLite → `codex-mock` → stdio → evidence → checkpoint | 81/81 локальных тестов PASS (Python 3.13/Linux) |
| 09.2 | Новая редакция Windows CI и PowerShell-демонстрация | NOT_RUN до публикации |

Файлы проверяются `SHA256SUMS.txt`; реальные OAuth-токены не использовались. Код `codex-app` остаётся неисполняемым, облачные модельные вызовы отсутствуют, автоматических разрешений не выдаётся. Личный Windows-хост, NVIDIA RTX 5070 Ti, Antigravity и BPR40 не затрагивались.
