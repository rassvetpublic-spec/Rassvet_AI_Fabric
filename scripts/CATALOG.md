# Реестр скриптов scripts/ (Script Registry)
> *Этот файл генерируется автоматически скриптом `scripts/generate_catalog.py`*

## Оформленные скрипты

| Имя файла | Тип | Описание |
|---|---|---|
| `Clone-RaiF-10_1-Safe-R2.ps1` | PowerShell | RAiF 10.1A R2: безопасный clone/check existing directory на Windows. |
| `demo-codex-mock.ps1` | PowerShell | Испытание SQLite-очереди и подставного Codex по stdio; никакого настоящего Codex или OAuth. |
| `demo-worktree-review.ps1` | PowerShell | RAiF 10.1: only Windows, Git and local deterministic validation. No provider calls. |
| `demo.ps1` | PowerShell | RAiF 10.2C: интеграционный smoke с надёжным разрешением Python. Выполняется только в одноразовом извлечённом дереве под D:\ЗАГРУЗКИ. |
| `QA-Clone-RaiF-10_1-Static-R2.ps1` | PowerShell | Статическая проверка запускатора 10.1A R2 штатным парсером Windows PowerShell. |
| `resolve-python.ps1` | PowerShell | Resolve a runnable Python; WindowsApps AppExecutionAliases can exist but fail (9009). |
| `run-tests.ps1` | PowerShell | RAiF integrated Windows test runner: preserve original PowerShell contract. Only the temporary integration projection receives this candidate. |
| `sidecar_passport_validator.py` | Python | 📋 Валидатор и гейт-контроллер Sidecar-паспортов по канону Архитектора (Sidecar Passports Gate). |
| `Test-RaiF-10_1B-Static.ps1` | PowerShell | Pure Windows PowerShell parse and literal-contract inspection. No Git, models or filesystem writes. |
| `Verify-RaiF-10_1B-Windows.ps1` | PowerShell | RAiF / 10.1B: Windows-only host acceptance of an EXISTING pinned clone. |
| `windows-preflight.ps1` | PowerShell | Проверка доступности компонентов Windows. Не читает профили, cookie и токены; не запускает модели. |
