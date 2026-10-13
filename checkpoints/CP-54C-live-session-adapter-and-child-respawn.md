# CP-54C — реализация нативного адаптера сессий и Child Respawn Hot-Switch

**Дата:** 2026-10-13  
**Статус:** `MODULES_READY / TESTS_PASS / PASSPORTS_VALID (26/26) / PILOT_READY`  
**Ветка:** `main`  
**Команда владельца:** `+mtd` ([▶️ Выполнить всё по очереди под MTD])

---

## 1. Контекст и архитектурное основание
- В соответствии с [RFC_ACCOUNT_SWITCH_MECHANICS](../design/RFC_ACCOUNT_SWITCH_MECHANICS.md) и [Master Plan CP-54](../design/RAiF_AG_Supervisor_Master_Implementation_Plan_CP54.md), прямой RPC-метод записи токена в `language_server.exe` отсутствует (`HostBridgeService.GetOAuthToken` является исключительно геттером).
- Утвержденная архитектура первого этапа — **Child Respawn hot-switch**:
  1. `Pre-write WinCred`: запись целевого JSON-блока в `gemini:antigravity` (Type=1, Persist=2, UserName="antigravity").
  2. `Terminate Child LS`: завершение только дочернего процесса `language_server.exe` (главное окно IDE и терминалы сохраняются).
  3. `Post-write WinCred`: повторная запись через 100 мс для защиты от перезаписи старым in-memory кэшем умирающего сервера.
  4. `Await Respawn`: ожидание автоматического респауна нового дочернего LS процессом `Antigravity.exe` (замер времени ~1.8 с).
  5. `Fail-closed Rollback`: немедленный возврат исходного снапшота при тайм-ауте или исключении.

---

## 2. Реализованные модули

1. **`src/raif_ag_supervisor/session_adapter.py`**
   - Нативная работа с Windows Credential Manager через `advapi32.dll` (`CredReadW`, `CredWriteW`, `CredDeleteW`, `CredFree`).
   - Управление дочерними процессами через `kernel32.dll` (`OpenProcess`, `TerminateProcess`, `CloseHandle`).
   - Метод `read_native_credential_json()` — чтение активного профиля с проверкой структуры.
   - Метод `write_native_credential_json()` — атомарная запись UTF-8 JSON.
   - Метод `execute_hot_switch()` — полный цикл Child Respawn с обязательным in-memory rollback.

2. **`src/raif_ag_supervisor/token_refresh.py`**
   - Каноническое форматирование в схему Antigravity `format_antigravity_credential_payload()`:
     - `token.access_token`, `token.token_type="Bearer"`, `token.refresh_token`, `token.expiry` (RFC 3339 UTC).
     - `auth_method="consumer"`, `id_token`.
   - Безопасное маскирование email (`mask_email()`).
   - Чтение локального кэша профилей `load_cached_profiles()`.
   - Сетевое обновление через Google OAuth2 endpoint `https://oauth2.googleapis.com/token`.

3. **`src/raif_ag_supervisor/hot_switcher.py`**
   - Координатор `HotSwitcher`:
     - Создание персистентного дискового снапшота в `%LOCALAPPDATA%\RAiF\AGSupervisor\rollback\pre-switch-*.raw` перед любыми модификациями.
     - Фильтрация и ранжирование кандидатов по остаточному TTL.
     - Выполнение переключения и возврат безопасного отчета `HotSwitchReport`.

---

## 3. Доказательства и валидация

- **Аудит локальных профилей:**
  - Обнаружено **9/9** профилей в кэше.
  - Все **9 профилей свежие** (остаточный TTL ~1600 секунд).
  - Активный нативный аккаунт `gemini:antigravity` подтвержден (BlobSize: 1422, UserName: antigravity).
  - Активный процесс Language Server: PID 26388 (`language_server.exe`).
- **Модульные тесты:**
  - `tests/test_session_adapter.py` (6/6 PASS, 0.79s).
  - `tests/test_hot_switcher.py` (2/2 PASS, 0.09s).
  - Интеграционный прогон супервизора: **54/54 PASS** (20.01s).
- **Sidecar-паспорта (`BPR40_SIDECAR_PASSPORT/1.1`):**
  - Созданы и валидированы: `session_adapter.passport.json`, `token_refresh.passport.json`, `hot_switcher.passport.json`.
  - Валидатор `scripts/sidecar_passport_validator.py`: **26/26 модулей валидны, 0 нарушений**.

---

## 4. Следующий шаг (Класс C)
- Запуск одного тестового переключения `hot_switcher.switch_to_candidate(candidate_index=0)` в живом сеансе с контролем респауна Language Server и проверкой сохранения текущего окна чата.
