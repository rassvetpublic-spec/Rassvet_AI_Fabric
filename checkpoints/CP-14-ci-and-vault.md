# CP-14 — GitHub CI и Vault Port

Дата: 2026-10-10

## Проверка
- Добавлен GitHub Actions workflow `.github/workflows/ag-supervisor-tests.yml`, Python 3.12, synthetic unittest.
- Прогон https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38000842996 завершился с conclusion=success на SHA ab49d195392c5e0d34d57b69ca4a6438916febec.
- Локальный clone не выполнен (DNS github.com недоступен), тесты запускались только в GitHub CI.

## Реализация
- Добавлен `src/raif_ag_supervisor/vault.py`: контракт CredentialVault, InMemoryTestVault, который принимает только синтетические значения и скрывает содержимое из repr.
- Добавлен `tests/test_vault.py`: три синтетических сценария. Новый прогон CI пока не подтверждён успешным.
- Никакие живые токены или файлы аккаунтов не использовались и не отправлялись в GitHub.
- Реальный Windows Credential Manager Adapter пока отсутствует; прототип не управляет Standalone.

## Курсор
AG_pather / CP-14 CI_BASELINE_PASS + VAULT_PORT_CREATED → CP-15 VERIFY_CI_TEST_VAULT → CP-16 WINDOWS_CREDENTIAL_ADAPTER → CP-17 STANDALONE_SANDBOX_VALIDATION.
