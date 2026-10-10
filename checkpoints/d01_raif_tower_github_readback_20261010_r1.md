# RAiF / Tower + GitHub — read-only сверка, R1

Дата: 10 октября 2026 г. Снимок: 2026-10-10T08:28:59.177084Z. **Класс:** проектное evidence, **не** authority Башни. Владелец: `rassvetpublic-spec/Rassvet_AI_Fabric`, ветка `AG_pather`. Базовый HEAD до записи: `5c602c7617ca051dcbc3f9c6705b8384882c3cdc`.

## 1. Источники и верификация
- **Действующая Башня**: Google Drive `CONTROL_TOWER`, [папка](https://drive.google.com/drive/folders/1d3boKYmIGgOqLEZB3nlHTt-sTl8i9QnW), исходный `control/current.yaml` получен непосредственно из Drive; SHA-256 полученных байт `4b29bc02ebd30fd5e5be27175000e2fcaa74f592b8def9f23c8fe05c0a3cfe37`. Файл сообщает `ACTIVE_BY_USER_DECISION` и `ultimate_responsible=USER`.
- **GitHub-реплика Башни**: `rassvetpublic-spec/CONTROL_TOWER`, main `b8d0e4f255b888a134091122b2d1db0a2c7d616c`, [control/current.yaml](https://github.com/rassvetpublic-spec/CONTROL_TOWER/blob/main/control/current.yaml). В файле `local_role=EXECUTION_REPLICA_NOT_AUTHORITY`, `active=false`, `production_sync=false`, `merge_requires=MTD`. Локальное `active=false` НЕ отключает действующую Drive authority.
- **BPR40**: Router v18 (`2026-10-05-BPR40-4.0.3`), BPR40 4.0.3 RELEASED. Сверены SHA-256 файлов `00_ROUTER.yaml` `e9d8cae1c371ba6cbac6904bda8d8070b86b7db76dab9d8486418ae639352cbd`, `BOOTSTRAP_BPR40_v1.yaml` `c1357cfba33b7f253f74f2e6b3bbb360465d427bc01f944c5410376df7865197`, `MANIFEST.json` `e5dad90670ab57206d944baafe51f66a06fa60deb439fbc648667fdb2229fcfc`, `CORE.yaml` `fbe51e299c4100bf2cf86d58d47849bdc794c8fd562185e2a82166cb21b4d10c`. Это проверка точных байт, не promotion нового протокола.
- **Drive Tower heartbeat** `TRI_TOWER_SYNC_HEARTBEAT.json`: снимок `2026-10-10T04:58:45.737881+00:00`, заявлено `SSD/BPR40/GDrive = 436/436/436`, `is_parity=true`, `replicated_files_count=0`. Это *сообщение источника о локальном паритете на момент снимка*, не независимая текущая приёмка production-sync GitHub ↔ Drive.
- Действующая Drive `00_README_TOWER.md` подтверждает назначение Башни и хранение различных деревьев; глобальное слияние исторических деревьев не объявляется. CKS/ANTIGRAVITY в README: `tested, not active`.

## 2. GitHub / PR #29 и недостающие gates
- [CONTROL TOWER PR #29](https://github.com/rassvetpublic-spec/CONTROL_TOWER/pull/29) остаётся `OPEN/DRAFT/NONCANON POINTER_ONLY`, head `24505a8bd7589894d7e50df81b9d6033096250ee`. Он ссылается на предыдущий проектный `CP54B2` и HEAD `ad722142b3c6e9e615314ac4237dfdc089765813`, а актуальный исходный HEAD проекта: `5c602c7617ca051dcbc3f9c6705b8384882c3cdc`. Это **историческая ссылка**, не действующий проектный курсор и не повод для бесконтрольного обновления PR.
- Протокол Башни: проектные checkpoint и volatile cursor принадлежат проекту; Башня содержит pointer/derived projection. Изменение Drive, Tower main, PR29 или авторизации разрешается только после `TOWER_SYNC_PREFLIGHT` и отдельного `USER_MTD_GATE`. Проверка источников сама по себе gate не открывает.
- `policies/repo-sync.yaml` и `github-load-governor.yaml` на GitHub Tower обозначены `P0_POLICY_PLACEHOLDER`; не использовать их как автоматическое разрешение на push, merge или синхронизацию.

## 3. Verdict, границы, следующий курсор
**Verdict:** `READBACK_COMPLETE_WITH_SCOPE / TOWER_GITHUB_SYNC_UNVERIFIED`. Изменения authority, Tower repo, Router/BPR40, CKS Canon и пользовательских аккаунтов: **0**.

**Текущий курсор:** `CONTROL_TOWER / NONCANON_RAIF_POINTER_READBACK_COMPLETE`.

**Следующий курсор Башни (только gate):** `CONTROL_TOWER / NONCANON_RAIF_POINTER_REVIEW → TOWER_SYNC_PREFLIGHT → USER_MTD_GATE`.

**Проектная линия:** см. парный `RAIF_BIGWAVE02_HANDOFF_2026-10-10_R1`; не дублировать оперативный cursor в authority Башни.
