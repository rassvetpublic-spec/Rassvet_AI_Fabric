# AG_pather — аудит патчеров Antigravity

Дата: 2026-10-10. Статус: частичная статическая проверка, патчи не запускались.

## CP-01 — GitHub и идентичность
- Целевой репозиторий: rassvetpublic-spec/Rassvet_AI_Fabric; ветка AG_pather создана от main (95122c90a4ac684e0ffba8b493001f7c4797d15a).
- QNIX-Dev/eligibility-antigravity-patcher доступен. Основной файл manager.py, blob SHA 544b1aa3e438804b02aa32bb395544cc6f2493ef. Лицензия MIT. На момент проверки: 114 stars, 16 forks, 2 open issues.
- AvenCores/open-antigravity-patcher: GitHub REST 404. Есть сторонние репозитории с похожими именами, авторство/происхождение не подтверждено. Сравнительная репутация AvenCores не проверена.

## CP-02 — частичный аудит manager.py
- Код использует Windows Credential Manager (ctypes) и SQLite state.vscdb; snapshot CLI/Manager сериализует учётные данные в Base64. Base64 НЕ шифрование. Источник: manager.py, строки 701–816.
- OAuth refresh: POST https://oauth2.googleapis.com/token, квоты POST https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary. Источник: manager.py, строки 960–1065.
- В просмотренном модуле network: фиксированные Google endpoints, блокирование редиректов с bearer/OAuth headers, HTTP timeout 15 сек, лимит ответа 1 MiB. Признаков отправки токена произвольному домену в этом модуле не найдено. Это не доказательство безопасности всего репозитория.
- Бинарный патчер содержит сигнатуры hasValidAuth для x64/arm64, резервные копии .agybak; источник: manager.py, строки 576–600 и константа BAK.
- Прямую поддержку AG-tools (отдельного продукта) и совместимость с установленной версией НЕ подтвердили.

## CP-03 — предварительный вердикт
- QNIX: опасность сохранения и переключения refresh tokens; защищать резервные копии и профили, не запускать с повышенными правами без необходимости.
- AvenCores: исходный оригинальный репозиторий недоступен по ранее данному URL; прежняя оценка его репутации отозвана до идентификации оригинала.
- Оба патчера не запускались; динамического анализа, проверки сетевого поведения процесса и анализа подписей нет.

## CURSOR
AG_pather / CP-03 complete → CP-04 provenance AvenCores → CP-05 full static diff → CP-06 AG-tools integration compatibility.

## TOKEN USAGE
Точный расход токенов модели за разговор и обращения к инструментам недоступен. Числовая оценка не выдаётся за фактический биллинг.
