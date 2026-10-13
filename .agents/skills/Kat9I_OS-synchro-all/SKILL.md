---
name: Kat9I_OS-synchro-all
description: Тотальная синхронизация всех Трёх Башен (SSD, GitHub, Google Drive) и 24 локальных Git-репозиториев флота Рассвет по команде /Катя-Синхро-всё или Kat9I_OS-synchro-all
---

# Глобальный скилл тотальной синхронизации флота (/Катя-Синхро-всё)

Канонический кросс-флотский навык автоматической сквозной синхронизации всех эшелонов хранения и кодовой базы флота Рассвет:
1. **Башня 1 (Локальный SSD):** 24 Git-репозитория в `C:\GIT`;
2. **Башня 2 (GitHub):** Удалённые репозитории организации `rassvetpublic-spec` (origin);
3. **Башня 3 (Google Drive):** Облачное зеркало `C:\Gdrive_RassvetPublic\CONTROL_TOWER`.

---

## 1. Команды вызова и синтаксис

Скилл активируется в любом чате и любом репозитории флота при вводе следующих команд или текстовых запросов:

- `/Катя-Синхро-всё`
- `Kat9I_OS-synchro-all`
- `/kat9i-synchro-all`
- `синхронизировать все башни + все локальные репо с github + gdrive`

### Поддерживаемые параметры и флаги:
- `--skip-tests`: пропустить запуск Quality Gate (только при экстренной синхронизации);
- `--skip-push`: выполнить аудит и локальное зеркалирование в Google Drive без отправки в GitHub;
- `--threads <N>`: число параллельных потоков robocopy для Google Drive (по умолчанию: `8`);
- `--json`: вывод отчёта в структурированном виде JSON.

---

## 2. Исполнительный контур (Execution Engine)

Скилл опирается на штатный мастер-оркестратор:

```powershell
py tools/sync/kat9i_synchro_all.py
```

### Пошаговый протокол работы:

### Шаг 1. Пакетная синхронизация 24 репозиториев Git (`C:\GIT`)
- Запуск [`tools/sync/fleet_git_sync.py`](file:///c:/GIT/CONTROL_TOWER/tools/sync/fleet_git_sync.py);
- Сканирование всех репозиториев: `AG25`, `AndreysSUNOBOT`, `antigravity-studio-pro`, `AntigravityData`, `asme-ptc19-3-tw-2016-batch`, `BPR40`, `chatbot-ui`, `CKS`, `ComfyUI-MusicMapper-nodes`, `ConnectorPIA-xray`, `DirectSUNO`, `Genre_test`, `KAT9I_OS`, `kat9i_skills`, `local-listener-android`, `media-collection`, `media-collection-clean`, `music-suite`, `OZONE12_MASTERING_LAB`, `pia-foss-desktop`, `rassvet-rules-hub`, `Rassvet_AI_Fabric`, `rassvetpublic-spec-kat9i_skills`, `CONTROL_TOWER`;
- Автоматическая фиксация канонических паспортов [`PROJECT_PASSPORT.yaml`](file:///c:/GIT/CONTROL_TOWER/PROJECT_PASSPORT.yaml);
- Отправка изменений в remote origin на GitHub (`git push origin <branch>`);
- Проверка целевого инварианта: **100% CLEAN** во всех репозиториях.

### Шаг 2. Оркестровка Трёх Башен (Tri-Tower Orchestrator)
- Запуск [`tools/sync/sync_tri_tower.py`](file:///c:/GIT/CONTROL_TOWER/tools/sync/sync_tri_tower.py);
- **Phase 1 (Quality Gate):** Прогон тестов `pytest tests protocols/bpr5/tests` (fail-closed при любой ошибке);
- **Phase 2 (GitHub Tower Sync):** Проверка чистоты рабочей копии и push ветки `main`;
- **Phase 3 (Google Drive Mirror):** Высокоскоростное зеркалирование многопоточным robocopy (`/MIR /MT:8`) с жесткой фильтрацией временных файлов, шума и блокировок SQLite (`*.sqlite-wal`, `*.sqlite-shm`, `*.lock`, `__pycache__`);
- **Cross-Fleet Parity:** Репликация шаблонов инициатив `INITIATIVE_TEMPLATE.md` в пиринговые репозитории `CKS` и `BPR40`;
- **Phase 4 (Receipt):** Опечатывание канонической квитанции паритета [`checkpoints/TRI_TOWER_SYNC_RECEIPT_CANONICAL_2026-10-11.json`](file:///c:/GIT/CONTROL_TOWER/checkpoints/TRI_TOWER_SYNC_RECEIPT_CANONICAL_2026-10-11.json).

### Шаг 3. Криптографический контроль деревьев Меркла (Merkle Tree O(1))
- Запуск [`protocols/bpr_evolution/BR-040.1/tri_tower_sync_daemon.py --once`](file:///c:/GIT/CONTROL_TOWER/protocols/bpr_evolution/BR-040.1/tri_tower_sync_daemon.py);
- Вычисление корней Меркла для трёх каталогов контрольных точек:
  - `SSD:` `C:\GIT\CONTROL_TOWER\checkpoints`
  - `BPR40:` `C:\GIT\BPR40\tasks\CROSS_REPO_COORDINATION_V1\checkpoints`
  - `GDrive:` `C:\Gdrive_RassvetPublic\CONTROL_TOWER\checkpoints`
- Проверка равенства: `Root(SSD) == Root(BPR40) == Root(GDrive)` при числе файлов `>= 218`;
- Фиксация статуса `is_parity: true` и `daemon_status: ACTIVE_PARITY_MAINTAINED` в [`checkpoints/TRI_TOWER_SYNC_HEARTBEAT.json`](file:///c:/GIT/CONTROL_TOWER/checkpoints/TRI_TOWER_SYNC_HEARTBEAT.json).

---

## 3. Гарантии и инварианты

1. **Safe Sync Gate:**
   `PRIVACY > SECURITY > DATA_INTEGRITY > KNOWLEDGE > AUTO-SYNC`. При любых коллизиях — немедленный откат и уведомление владельца.
2. **Нулевой дрейф контрактов (Contract Drift Zero):**
   Все скрипты оркестратора оснащены Sidecar-паспортами `BPR40_SIDECAR_PASSPORT/1.1`.
3. **Строгая эпистемическая честность:**
   `UNKNOWN != PASS`. Непроверенное состояние репозитория не считается чистым.
4. **Соблюдение матрицы владения скилами (`SKILL_OWNERSHIP_MATRIX`):**
   Скилл принадлежит Срою 1 (Git Repositories SSOT) и тиражируется по всем репозиториям флота.
