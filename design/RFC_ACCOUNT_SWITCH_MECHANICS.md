# RFC: Сравнительный аудит 6 доноров решений и выбор механики переключения Google-аккаунтов без перезапуска Antigravity

* **Статус**: APPROVED FOR IMPLEMENTATION — внутреннее направление владельца; provider eligibility и live acceptance открыты  
* **Дата**: 2026-10-10  
* **Область**: `raif_ag_supervisor` / Windows Antigravity Standalone 2.22.0.0  
* **Целевой Issue**: [#2](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/issues/2)  

**Граница доказательств, MTD 011011:** архитектуры Child Respawn и Reverse Proxy утверждены для проектирования и изолированной проверки; описанные ниже времена `1.5–1.8 с`, `<100 мс`, «0 секунд простоя» и бесшовный SSE replay — **целевые гипотезы**, не результаты подтверждённых live-испытаний. `403` не всегда означает quota; нужен provider reason. Работа с реальными сессиями и токенами допускается только через проверенный провайдером интерфейс и отдельный пользовательский gate.

---

## 1. Контекст и проблема

При интенсивной разработке с использованием моделей Gemini в Google Antigravity пользователи регулярно сталкиваются с исчерпанием лимитов квот (`HTTP 429 Too Many Requests` или `HTTP 403 RESOURCE_EXHAUSTED`).

Для обеспечения непрерывной и продуктивной работы требуется автоматическая ротация учетных записей из локального пула (`AccountPool`). Однако стандартный механизм смены аккаунта в Antigravity требует ручного выхода через браузер или полного перезапуска приложения, что приводит к:
* Закрытию главного окна IDE, потере несохранённых буферов и сбросу терминалов;
* Обрыву текущих длинных генераций кода;
* Задержкам на повторный запуск (10–20 секунд).

**Цель RFC**: на основе детального аудита исходного кода 6 известных открытых доноров внедрить в `raif_ag_supervisor` архитектурное решение для автоматического переключения Google-аккаунтов **без перезапуска Antigravity**.

---

## 2. Сводная матрица аудита исходных кодов на GitHub

Прямой анализ репозиториев показал реальные механизмы работы каждого донора:

| Донор | Заявлено | Реальный механизм в коде | Без рестарта? | Вердикт для RAiF |
| :--- | :---: | :--- | :---: | :--- |
| **demusraph/antigravity-control-center** | Standalone, 429 + CDP | `WinCred` + **скрытый `taskkill /F`** + перезапуск AG + клик через CDP (порт 9222) | **ФИКТИВНО** (рестарт маскируется) | Использовать модуль **CDP-автоматизации клика**, но исключить механизм смены. |
| **Muriel-Gasparini/antigravity-account-switcher** | Linux 2.0, 429 + replay | **Scoped HTTP/gRPC Reverse Proxy** с in-flight перехватом 429 и повтором запроса | **ДА (Истинный hot-swap)** | **Лучший архитектурный донор**. Адаптировать Loopback Reverse Proxy под Windows для прозрачного перехвата 429. |
| **lbjlaq/Antigravity-Manager** (AG-tools) | API Gateway / GUI | `gemini:antigravity` + респаун дочернего LS для IDE. Для Standalone — жёсткий `close_antigravity` | **ДА для дочернего LS** | Заимствовать паттерн **Pre-write → kill child LS → Post-write** для быстрой реализации (Фаза 1). |
| **QNIX-Dev/eligibility-antigravity-patcher** | CLI / IDE | Байт-патчер `hasValidAuth`. Блокирует смену при живом процессе (`_accounts_busy`) | **НЕТ** (требует рестарт) | Донор сигнатур снятия гео-блокировок. К бесшовной ротации непригоден. |
| **Doomd/antigravity-account-switcher** | IDE Windows | VSIX + PowerShell профили, toast-уведомление при 429 | **НЕТ** (рестарт IDE) | Полезен паттерн сохранения вкладок в `pending_state.json` как аварийный контур. |
| **AvenCores/open-antigravity-patcher** | CLI / IDE | Байт-патчер (SourceForge V1.3.8, GitHub 404) | **НЕТ** (нет ротации) | Форк раннего QNIX без ротации. |

---

## 3. Детальный разбор доноров

### 3.1. demusraph Control Center — скрытый `taskkill`
* **Файлы**: `src/antigravity_switcher/app.py`, `switcher.py`, `daemon.py`
* В `app.py` функция `switch_to_account_core()` вызывает принудительный `taskkill /F /IM Antigravity.exe`.
  «Бесшовность» имитируется подключением по Chrome DevTools Protocol (`--cdp_port=9222`) и программным кликом на «Retry» после перезапуска.
* **Оценка**: Метод грубый, ломает терминалы и отладку. Полезен только алгоритм подключения по CDP для нажатия «Повторить» при сетевых сбоях.

### 3.2. Muriel-Gasparini — эталонная архитектура Hot-Swap (Loopback Proxy)
* **Файлы**: `internal/proxy/handler.go`, `internal/proxy/failover.go`, `internal/launcher/wrap.go`
* **Архитектура**:
  1. Приложение запускается через обёртку с перенаправлением трафика на локальный прокси:
     ```bash
     HTTP_PROXY = "http://127.0.0.1:" + proxyPort
     HTTPS_PROXY = "http://127.0.0.1:" + proxyPort
     CLOUD_CODE_URL = "http://127.0.0.1:" + proxyPort
     ```
  2. Локальный прокси перехватывает вызовы к `daily-cloudcode-pa.googleapis.com` и буферизирует тело запроса в памяти (`io.Reader`).
  3. При получении `HTTP 429` или `403 RESOURCE_EXHAUSTED` срабатывает `FailoverEngine`:
     * Выбирает следующий валидный аккаунт из пула `AccountPool`.
     * Подменяет заголовок `Authorization: Bearer <new_token>`.
     * Выполняет **прозрачный replay (повтор) исходного запроса**.
  4. Стрим SSE возвращается в Antigravity без разрыва сессии.
* **Оценка**: Antigravity вообще не замечает смену аккаунта, генерация не прерывается, 0 секунд простоя.

### 3.3. lbjlaq AG-tools — трюк двойной записи при респауне Language Server
* **Файл**: `src-tauri/src/modules/integration.rs`
* Алгоритм респауна дочернего Language Server:
  * **Проблема гонки**: умирающий Language Server при получении `SIGTERM/taskkill` может успеть сбросить старый in-memory токен обратно в хранилище, перезатерев новый.
  * **Решение**:
    1. Записать новые credentials в `gemini:antigravity`.
    2. Убить **только дочерний процесс** `language_server.exe` (`taskkill /F /IM language_server.exe`). Главное окно `Antigravity.exe` не закрывается.
    3. Повторно выполнить запись credentials (Post-kill assertion).
    4. Antigravity автоматически перезапускает дочерний LS за 1.5–1.8 секунды, считывая новый токен.
* **Результаты статического RPC-аудита (`language_server.exe`)**:
  В protobuf-дескрипторах обнаружено 324 RPC в `LanguageServerService` и методы `HostBridgeService.GetOAuthToken`, `GetAuthStatus`, `RetrieveUserQuotaSummary`. Однако **прямой RPC-метод записи токена (`SwitchAccount` / `SetAuthToken`) отсутствует**, а `HostBridgeService.GetOAuthToken` является геттером. Поэтому управление через Credential Manager + респаун дочернего LS или Reverse Proxy — единственные жизнеспособные пути.

---

## 4. Сравнительный анализ архитектур для RAiF

| Критерий | Вариант А: Child Respawn (lbjlaq / Фаза 1) | Вариант Б: Loopback Proxy (Muriel-Gasparini / Фаза 2) |
| :--- | :--- | :--- |
| **Сохранение окна IDE** | Полное (главное окно не закрывается) | Полное (главное окно не закрывается) |
| **Поведение стрима при 429** | Текущий стрим падает, следующий идёт с нового аккаунта | **Стрим не падает** (мгновенный in-flight replay) |
| **Скорость переключения** | 1.5 – 2.0 секунды | **< 100 миллисекунд** |
| **Сложность внедрения** | Минимальная (~15 строк кода в `raif_ag_supervisor`) | Средняя (встроенный локальный HTTP/gRPC прокси) |
| **Зависимость от WinCred** | Прямая (атомарная запись в `gemini:antigravity`) | Отсутствует (токены ротируются в памяти прокси) |

---

## 5. Двухфазная дорожная карта внедрения

### Фаза 1. Быстрый Hot-Switch (Внедрение в `raif_ag_supervisor`)
* Реализовать метод `hot_switch_antigravity_account()` на основе алгоритма двойной записи:
  `Pre-write WinCred` → `Kill language_server.exe` → `Post-write WinCred`.
* Главное окно `Antigravity.exe`, вкладки и терминалы остаются открытыми.
* При исчерпании квот (429/403) супервизор берёт следующий токен из пула `AccountPool` и перезапускает только дочерний процесс. Время смены — ~1.8 с.
* Использовать аварийный rollback из `CP-52D` при сбоях.

### Фаза 2. Целевая архитектура: In-Flight Loopback Reverse Proxy
* Разработать встроенный легковесный **Loopback Reverse Proxy** в `raif_ag_supervisor` по паттерну Muriel-Gasparini:
  * Прокси на `127.0.0.1:<port>` перехватывает трафик к Google Cloud Code API.
  * Буферизация тела запроса и мгновенный transparent replay со сменой Bearer-токена при получении 429.
  * Нулевое время простоя генерации, стримы не прерываются.
  * Интеграция страховочного CDP-кликера из `demusraph` на случай клиентских таймаутов интерфейса.
