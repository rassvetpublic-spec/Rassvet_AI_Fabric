# CP-26 — формальные критерии горячего переключения Standalone

Дата: 2026-10-10
Ветка: AG_pather

## Реализация
- `src/raif_ag_supervisor/verification.py` — проверка результатов handoff через предоставленные извне свидетельства, не выполняет переключение и не читает секреты.
- Условия полного VERIFIED: тот же экземпляр language_server (PID + маркер времени создания), независимо подтверждённая смена внутреннего account handle и доказанное продолжение активной задачи.
- Раздельные состояния: inconclusive, process_restarted, account_unchanged, wrong_account, account_changed_stream_unproven, verified.
- `src/raif_ag_supervisor/session_probe.py` расширен чтением Windows FILETIME создания процесса через GetProcessTimes с правом PROCESS_QUERY_LIMITED_INFORMATION. Не читает память процесса.
- `tests/test_verification.py` и новые тесты process marker проверяют синтетические положительные и отрицательные сценарии.

## Предупреждение
- Указание `identity_verified=True` в синтетическом тесте не доказывает реальную авторизацию. Надёжный Windows observer ещё не существует.
- Отсутствует реализация собственно hot swap; нет подтверждения сохранения потока при переключении.
- Удалённый доступ Desktop Commander к RASSVET_DESKTOP был заблокирован месячным лимитом. Реальные аккаунты и приложение не изменялись.
- Никакие OAuth токены или email не использовались.

## Бюджет GitHub Actions
- Обычные коммиты в AG_pather не запускают CI.
- CP-23: разовый Linux+Windows success; CP-24: разовый Linux-only success.
- Для CP-26 нужен один пакетный Linux+Windows контрольный прогон после фиксации исходников.

## Текущий курсор
AG_pather → CP-26 BATCHED_TEST_PENDING → CP-27 LOCAL_AUTH_OBSERVER_DESIGN → CP-28 RASSVET_DESKTOP_RUNTIME_VALIDATION.
