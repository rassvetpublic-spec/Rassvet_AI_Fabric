# Исследованные инженерные практики

**Статус:** техническая записка (не часть главной страницы проекта). **Дата:** 10 октября 2026 года.

Проект создаётся независимо. Эти внешние open-source решения использовались как предмет изучения **паттернов**, а не как устанавливаемая базовая runtime-зависимость.

| Исходный проект | Лицензия | Изучаемые паттерны | Собственная реализация Fabric |
|---|---|---|---|
| [oh-my-codex](https://github.com/Yeachan-Heo/oh-my-codex) | MIT | Team orchestration, durable goals, hooks, HUD, subagent profiles, event/state traces | Task Graph, worker adapter, наблюдаемость и checkpoint gate |
| [Superpowers](https://github.com/obra/superpowers) | MIT | Brainstorming, specification, planning, TDD, subagent-driven implementation, worktrees, review | Проверяемая методология разработки и аудит результатов |

Упоминания этих проектов намеренно **не включены в `README.md`**. Если в будущем будет заимствован исходный код MIT-проектов, необходимо сохранить соответствующие copyright/license notices в поставке и отметить точный upstream-коммит/файл, независимо от расположения текста в README. До такого решения исходники доноров не встраиваются в пакет.
