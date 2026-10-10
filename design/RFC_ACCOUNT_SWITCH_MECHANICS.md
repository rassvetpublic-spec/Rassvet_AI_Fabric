# RFC: Сравнительный аудит 6 доноров решений и выбор механики переключения Google-аккаунтов без перезапуска Antigravity

* **Статус**: PROPOSED  
* **Дата**: 2026-10-10  
* **Область**: `raif_ag_supervisor` / Windows Antigravity Standalone 2.22.0.0  
* **Целевой Issue**: [#2](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/2)

---

## 1. Контекст и проблема

При интенсивной разработке с использованием моделей Gemini в Google Antigravity пользователи регулярно сталкиваются с лимитами квот (`HTTP 429 Too Many Requests` или `HTTP 403 RESOURCE_EXHAUSTED`).

Для обеспечения непрерывной работы требуется ротация учетных записей из локального пула (`AccountPool`). Однако стандартный механизм смены аккаунта в Antigravity требует ручного выхода, браузерного OAuth или полного перезапуска приложения, что приводит к:
* Закрытию главного окна IDE, потере несохранённых буферов и сбросу терминалов;
* Обрыву текущих длинных генераций кода;
* Задержкам на повторный запуск (10–20 секунд).

**Цель RFC**: на основе прямого аудита исходного кода 6 известных открытых доноров определить и формализовать архитектурное решение для переключения Google-аккаунтов **без перезапуска Antigravity**.

---

## 2. Сводная матрица аудита исходных кодов на GitHub

Прямой анализ репозиториев показал, что реальное поведение кода принципиально отличается от маркетинговых описаний в README:

| Донор | Заявлено | Реальный механизм в коде | Без рестарта? | Вердикт для RAiF |
| :--- | :---: | :--- | :---: | :--- |
| **demusraph/antigravity-control-center** | Standalone, 429 + CDP | `WinCred` + **скрытый `taskkill /F`** + перезапуск AG + клик через CDP (порт 9222) | **ФИКТИВНО** (рестарт маскируется) | Использовать модуль **CDP-автоматизации клика**, но исключить механизм смены. |
| **Muriel-Gasparini/antigravity-account-switcher** | Linux 2.0, 429 + replay | **Scoped HTTP/gRPC Reverse Proxy** с in-flight перехватом 429 и повтором запроса | **ДА (Истинный hot-swap)** | **Лучший архитектурный донор**. Адаптировать прокси под Windows. |
| **lbjlaq/Antigravity-Manager** (AG-tools) | API Gateway / GUI | `gemini:antigravity` + респаун дочернего LS для IDE. Для Standalone — жёсткий `close_antigravity` | **НЕТ** (для Standalone рестарт) | Заимствовать паттерн **Pre-write → kill child LS → Post-write**. Не брать шлюз целиком. |
| **QNIX-Dev/eligibility-antigravity-patcher** | CLI / IDE | Байт-патчер `hasValidAuth`. Блокирует смену при живом процессе (`_accounts_busy`) | **НЕТ** (требует рестарт) | Донор сигнатур снятия гео-блокировок. К бесшовной ротации непригоден. |
| **Doomd/antigravity-account-switcher** | IDE Windows | VSIX + PowerShell профили, toast-уведомление при 429 | **НЕТ** (рестарт IDE) | Полезен паттерн сохранения вкладок в `pending_state.json` как аварийный контур. |
| **AvenCores/open-antigravity-patcher** | CLI / IDE | Байт-патчер (SourceForge V1.3.8, GitHub 404) | **НЕТ** (нет ротации) | Форк раннего QNIX без ротации. |

---

## 3. Детальный разбор доноров

### 3.1. demusraph Control Center — скрытый `taskkill`
* **Файлы**: `src/antigravity_switcher/app.py`, `switcher.py`, `daemon.py`
* В `app.py` функция `switch_to_account_core()` вызывает:
  ```python
  def stop_antigravity():
      subprocess.run(["taskkill", "/F", "/IM", "Antigravity.exe"])
  ```
  Заявление о работе «без рестарта» основано исключительно на том, что `daemon.py` после принудительного убийства процесса Antigravity и обновления токена в `WinCred` подключается по Chrome DevTools Protocol (`--cdp_port=9222`, считывая `%APPDATA%\Antigravity\DevToolsActivePort`) и нажимает кнопку «Retry» в открывшемся заново окне.
* **Оценка**: Метод грубый, ломает терминалы и отладку, не является бесшовным.

### 3.2. Muriel-Gasparini — эталонная реализация Hot-Swap
* **Файлы**: `internal/proxy/handler.go`, `internal/proxy/failover.go`, `internal/launcher/wrap.go`
* **Архитектура**:
  1. Приложение запускается через обёртку с проксированием:
     ```go
     HTTP_PROXY = "http://127.0.0.1:" + proxyPort
     HTTPS_PROXY = "http://127.0.0.1:" + proxyPort
     CLOUD_CODE_URL = "http://127.0.0.1:" + proxyPort
     ```
  2. Прокси слушает вызовы к `https://daily-cloudcode-pa.googleapis.com` и буферизирует тело запроса в памяти (`io.Reader`).
  3. `failover.go` ловит `HTTP 429` или `403 RESOURCE_EXHAUSTED`.
  4. Запускается `FailoverEngine`:
     * Шаг 1: `ActionFallbackSecondary` — пробует резервную модель (Flash вместо Pro) на том же аккаунте.
     * Шаг 2: `ActionRotateAccount` — ротирует аккаунт в SQLite, подменяет `Authorization: Bearer <new_token>` и выполняет **прозрачный replay исходного запроса**.
  5. Стрим SSE возвращается клиенту.
* **Оценка**: Приложение Antigravity вообще не подозревает о смене аккаунта, стрим генерации не прерывается.

### 3.3. lbjlaq AG-tools — трюк двойной записи при респауне Language Server
* **Файл**: `src-tauri/src/modules/integration.rs`
* **Ключевая находка**: в коде для IDE описан алгоритм «热切号» (Hot switch):
  * **Проблема гонки**: умирающий Language Server при получении `SIGTERM/taskkill` может успеть сбросить старый in-memory токен обратно в файл или реестр, перезатерев свежезаписанный.
  * **Решение**:
    1. Записать новые credentials в `gemini:antigravity`.
    2. Убить **только дочерний процесс** `language_server.exe` (главное окно `Antigravity.exe` не трогается).
    3. Повторно выполнить запись credentials (Post-kill assertion).
    4. Встроенный супервизор IDE перезапускает дочерний LS за 1.5–2 секунды, подхватывая новый токен.
* **Причина сбоя на Standalone**: в строке 312 стояло условие `if is_ide && running`. Для Standalone автор ошибочно прописал ветку с полным `close_antigravity()`, хотя Standalone 2.22.0 точно так же умеет перезапускать дочерний сервер.

---

## 4. Сравнительный анализ архитектур для RAiF

| Критерий | Вариант А: Child Respawn (CP-53 + AG-tools) | Вариант Б: Loopback Proxy (Muriel-Gasparini) |
| :--- | :--- | :--- |
| **Сохранение окна IDE** | Полное (окно не закрывается) | Полное (окно не закрывается) |
| **Поведение стрима при 429** | Текущий стрим падает, следующий идёт с нового аккаунта | **Стрим не падает** (in-flight replay) |
| **Скорость переключения** | 1.5 – 3.0 секунды | **< 100 миллисекунд** |
| **Сложность внедрения** | Низкая (готова к пилоту в CP-53) | Средняя (требуется локальный HTTP-прокси) |
| **Зависимость от WinCred** | Прямая (требуется атомарная запись DPAPI) | Отсутствует (токены живут в памяти прокси) |

---

## 5. Двухфазная дорожная карта внедрения

### Фаза 1. Быстрый результат (Стабилизация CP-53)
* Использовать механизм **Child Respawn** с трюком двойной записи из `lbjlaq`:
  `Pre-write WinCred` → `Kill language_server.exe` → `Post-write WinCred`.
* Сохранить главное окно IDE открытым.
* Использовать аварийный rollback из `CP-52D` при сбоях.

### Фаза 2. Целевая архитектура (Продакшн CP-54+)
* Реализовать встроенный легковесный **Loopback Reverse Proxy** в `raif_ag_supervisor` на базе паттерна `Muriel-Gasparini`:
  * Перехват эндпоинта `--cloud_code_endpoint` через локальный порт `127.0.0.1:<port>`.
  * Буферизация исходящих запросов и автоматический повтор с токеном преемника из `AccountPool` при 429.
  * Интеграция страховочного механизма **CDP Resume** (из `demusraph`) на случай клиентских таймаутов.
