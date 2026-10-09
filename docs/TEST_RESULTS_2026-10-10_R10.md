# Протокол испытаний R10 — приёмка 09.4 на Windows

**Дата:** 10 октября 2026 года. **Источник:** GitHub Actions [запуск №38001948018](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38001948018) для коммита `8cf59a9a96ca0fa97998c14f5265cea573f015fb` (Git-дерево `ca554a520ca07cab4fbfc53d590cf52c1b0d8e01`).

## Подтверждение

| Среда | Результат | Пропуски |
|---|---|---|
| GitHub-hosted Windows / Python 3.11 | **116/116 PASS** | 0 |
| GitHub-hosted Windows / Python 3.13 | **116/116 PASS** | 0 |

Проверены корректная и ошибочная криптографическая валидация JWT по тестовым RSA-ключам; метаданные упаковки; планирование путей; реальный Windows API `CryptProtectData` / `CryptUnprotectData` на вымышленном BLOB. Гарантии получения доверенного JWKS с сервера и сохранности реальных токенов пока **не** подтверждены.

## История ошибки

Первый CI [№38001746366](https://github.com/rassvetpublic-spec/Rassvet_AI_Fabric/actions/runs/38001746366) завершился FAILED из-за неверного положения `license` в `pyproject.toml`. Дефект исправлен в `8cf59a9`; добавлены два теста, проверяющие секции метаданных. Это оставлено в истории проекта для воспроизводимости.

## Строгая граница PASS

- **PASS:** тесты офлайн-подписи ID-токена и DPAPI-прототипа текущего пользователя.
- **НЕ ВЫПОЛНЕНО:** реальный вход, token exchange, защищённая запись OAuth-токенов, ACL-readback, получение JWKS по HTTPS, inference, квоты подписки, личный Windows-хост, публикация в BPR40/три башни.

**Следующий курсор:** `RAI-FABRIC/09.5-TRUSTED_JWKS_AND_VAULT_PERSISTENCE`.
