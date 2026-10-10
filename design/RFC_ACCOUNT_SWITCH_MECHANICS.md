# RFC: Сравнительный аудит 6 доноров решений и выбор механики переключения Google-аккаунтов без перезапуска Antigravity

* **Статус**: RESEARCH / NEEDS_VALIDATION  
* **Дата**: 2026-10-10  
* **Область**: `raif_ag_supervisor` / Windows Antigravity Standalone 2.22.0.0  
* **Целевой Issue**: [#2](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/2)  
* **Нормативная база**: [PRODUCT_SCOPE.md](../docs/PRODUCT_SCOPE.md) (запрет обхода квот ротацией потребительских аккаунтов)

---

## 1. Контекст и границы исследования

При интенсивной разработке с использованием Google Antigravity возникает необходимость управления профилями и рабочими контекстами. 

> [!IMPORTANT]
> **Ограничение политик (PRODUCT_SCOPE.md)**:
> В соответствии с `docs/PRODUCT_SCOPE.md` (раздел 2 и 5), Rassvet AI Fabric **запрещает** автоматическую ротацию потребительских аккаунтов ради обхода исчерпанных лимитов через сторонний API-прокси.
> Цель данного RFC — **технический аудит существующих механик переключения профилей (donor forensics)** для реализации легитимного переключения рабочих профилей (workspace/enterprise handoff), сохранения рабочего контекста (checkpoint/resume) и мониторинга состояния авторизации, а не построение инструмента обхода квот.

Стандартный механизм смены аккаунта в Antigravity требует ручного выхода, браузерного OAuth или полного перезапуска приложения, что приводит к:
* Закрытию главного окна IDE, потере несохранённых буферов и сбросу терминалов;
* Обрыву текущих длинных генераций кода;
* Задержкам на повторный запуск (10–20 секунд).

**Цель RFC**: на основе прямого аудита исходного кода 6 известных открытых доноров классифицировать механизмы смены профиля и определить валидируемый путь для `raif_ag_supervisor`.

---

## 2. Сводная матрица аудита исходных кодов на GitHub

Прямой анализ репозиториев показал, что реальное поведение кода принципиально отличается от маркетинговых описаний в README:

| Донор | Заявлено | Реальный механизм в коде | Без рестарта? | Вердикт для RAiF |
| :--- | :---: | :--- | :---: | :--- |
| **demusraph/antigravity-control-center** | Standalone, 429 + CDP | `WinCred` + **скрытый `taskkill /F`** + перезапуск AG + клик через CDP (порт 9222) | **ФИКТИВНО** (рестарт маскируется) | Использовать модуль **CDP-автоматизации клика**, но исключить механизм смены. |
| **Muriel-Gasparini/antigravity-account-switcher** | Linux 2.0, 429 + replay | **Scoped HTTP/gRPC Reverse Proxy** с in-flight перехватом 429 и повтором запроса | **ДА (в Linux-окружении)** | **Отклонено для реализации**: нарушает `PRODUCT_SCOPE.md`; replay на Windows Standalone не доказан. |
| **lbjlaq/Antigravity-Manager** (AG-tools) | API Gateway / GUI | `gemini:antigravity` + респаун дочернего LS для IDE. Для Standalone — жёсткий `close_antigravity` | **ГИПОТЕЗА** (только для IDE) | Паттерн **Pre-write → kill child LS → Post-write** требует строгой экспериментальной проверки (G1). |
| **QNIX-Dev/eligibility-antigravity-patcher** | CLI / IDE | Байт-патчер `hasValidAuth`. Блокирует смену при живом процессе (`_accounts_busy`) | **НЕТ** (требует рестарт) | Донор сигнатур снятия гео-блокировок. К бесшовной ротации непригоден. |
| **Doomd/antigravity-account-switcher** | IDE Windows | VSIX + PowerShell профили, toast-уведомление при 429 | **НЕТ** (рестарт IDE) | Полезен паттерн сохранения вкладок в `pending_state.json` как аварийный контур. |
| **AvenCores/open-antigravity-patcher** | CLI / IDE | Байт-патчер (SourceForge V1.3.8, GitHub 404) | **НЕТ** (нет ротации) | Форк раннего QNIX без ротации. |

---

## 3. Детальный разбор доноров

### 3.1. demusraph Control Center — скрытый `taskkill`
* **Файлы**: `src/antigravity_switcher/app.py`, `switcher.py`, `daemon.py`
* В `app.py` функция `switch_to_account_core()` вызывает принудительный `taskkill /F /IM Antigravity.exe`.
  «Бесшовность» имитируется подключением по Chrome DevTools Protocol (`--cdp_port=9222`) и программным кликом на «Retry» после перезапуска.
* **Оценка**: Метод грубый, ломает терминалы и отладку.

### 3.2. Muriel-Gasparini — Scoped Proxy и его ограничения
* **Файлы**: `internal/proxy/handler.go`, `internal/proxy/failover.go`, `internal/launcher/wrap.go`
* **Архитектура**: Scoped HTTP/gRPC Reverse Proxy с буферизацией тела запроса и подменой `Authorization: Bearer` при получении HTTP 429.
* **Оценка для RAiF**:
  1. **Policy Gate**: Противоречит `PRODUCT_SCOPE.md` (автоматическая ротация ради обхода квот через прозрачный proxy исключена из скоупа проекта).
  2. **Технические риски**: Отсутствуют доказательства сохранения целостности уже идущего SSE-потока на Windows Standalone при подмене токена; повтор запроса после 429 может дублировать побочные эффекты.

### 3.3. lbjlaq AG-tools — анализ механизма Child Respawn
* **Файл**: `src-tauri/src/modules/integration.rs`
* Алгоритм респауна дочернего Language Server:
  1. Записать новые credentials в `gemini:antigravity`.
  2. Убить дочерний процесс `language_server.exe` (`taskkill /F`).
  3. Повторно подтвердить запись credentials (Post-kill assertion для защиты от сброса in-memory токена).
* **Статус**: В коде AG-tools это условие изолировано веткой `if is_ide && running`. Для Standalone автор использовал полный перезапуск. Перенос поведения на Standalone является **исследовательской гипотезой**, требующей проверки через Gate G1.
* **Результаты статического RPC-аудита (`language_server.exe`)**:
  В извлечённых protobuf-дескрипторах обнаружено 324 RPC в `LanguageServerService` и методы `HostBridgeService.GetOAuthToken`, `GetAuthStatus`, `RetrieveUserQuotaSummary`. Однако **прямой RPC-метод записи/смены токена (`SwitchAccount` / `SetAuthToken`) отсутствует**. `HostBridgeService.GetOAuthToken` является геттером.

---

## 4. Сравнительный анализ архитектур для RAiF

| Критерий | Гипотеза А: Child Respawn (AG-tools) | Гипотеза Б: Loopback Proxy (Muriel-Gasparini) | Базовый вариант: Session Handoff + State Checkpoint |
| :--- | :--- | :--- | :--- |
| **Статус валидации** | Не проверено на Standalone (0 успешных переключений в CP-53) | Не проверено на Windows; заблокировано политиками | **Соответствует архитектуре RAiF** |
| **Соответствие PRODUCT_SCOPE** | Допустимо при ручной смене рабочего профиля | **ЗАПРЕЩЕНО** (обход квот через proxy) | **Полное соответствие** |
| **Сохранение окна IDE** | Заявлено, требует подтверждения в G1 | Теоретически полное | Восстановление через checkpoint/resume |
| **Риск потери данных/состояния** | Средний (гонка записи в CredMan) | Высокий (дублирование запросов/сбои TLS) | Нулевой (атомарный rollback snapshot) |

---

## 5. Дорожная карта исследований и валидации (CP-54)

Вместо внедрения непроверенного Bearer-прокси проект следует строгой программе валидации:

### Шаг 1. CP-54A1 — Read-Only Local RPC Observer
* Подключение к подтверждённым локальным интерфейсам `language_server.exe` / `HostBridge`.
* Строго **read-only**: мониторинг статуса авторизации (`GetAuthStatus`, `GetUserStatus`), без мутаций.
* Полный запрет на логирование CSRF-токенов, OAuth-секретов и полезной нагрузки RPC.

### Шаг 2. Gate G1 — Проверка гипотезы Handoff / Session Reload
* Проверить, существует ли поддерживаемый механизм перезагрузки сессии без полного рестарта.
* Тестирование только на **2 профилях с обязательным проверенным rollback** (возврат в исходное состояние).
* Фиксация одного из официальных статусов:
  * `RESTART_SWITCH_VERIFIED` — стабильная смена с перезапуском и сохранением вкладок.
  * `HOT_SWAP_VERIFIED` — подтверждённое переключение только дочернего LS.
  * `UNSUPPORTED` — отсутствие безопасного механизма без штатного UI.

### Шаг 3. Целевой режим: User-Controlled Handoff + Checkpoint/Resume
* Если безопасный hot-swap API не подтверждён — реализация предсказуемого пользовательского переключения с сохранением контекста задачи (`Task Graph / Checkpoint Bridge`), без скрытых убийств процессов и без прозрачных прокси.
