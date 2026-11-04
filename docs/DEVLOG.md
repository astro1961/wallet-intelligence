# DEVLOG — Wallet Intelligence Tracker

Подробный рабочий лог: что сделано, чем проверено, какие решения приняты и почему.
Формат записи: дата/время (+04), этап, действие, команда, результат, выводы.

---

## 2026-11-04 17:52 — Старт проекта

**Вход:** `~/Downloads/wallet_intelligence_tracker_spec.md` (ТЗ v1.0, 1028 строк,
Python 3.12+, Textual, SQLite, SQLAlchemy, Alembic, Pydantic, HTTPX, NetworkX, Pytest).
Указание пользователя: проект в `~/Projects/`, критерии приёмки — на усмотрение Hermes,
главное работоспособность; спорные моменты фиксировать в логе; вести подробный лог;
ретро — позже.

**Сделано:**
- `git init` в `~/Projects/wallet-intelligence`;
- копия ТЗ → `docs/spec.md`;
- `docs/PLAN.md` — 8 этапов (1 разбит на 1A/1B), процесс TDD + независимый гейт,
  12 критериев приёмки A1–A12;
- `acceptance/gate_stage1a.py` — независимый гейт Этапа 1A (13 проверок);
- `tasks/stage1a.md` — задание агенту с закреплёнными контрактами API/моделей.

**Окружение (проверено):**
- `agy 1.4.12`, OAuth живой (`agy -p "Reply with exactly: AGY_OK"` → `AGY_OK`);
- Python 3.14.9 системный; глобального `pytest` нет; `uv` 0.x установлен;
- `git`, `node`, `npm` в наличии.

**Зафиксированные хеши (sha256) — гейт неизменяем:**
```
b1f6d227df96b3d4b4df58d40deb25720093c9f71426944a63d9f9c25d72934b  acceptance/gate_stage1a.py
cbd225716e690bc7f6e67898825b73b290bca09a461468fc888253cd0689d82b  tasks/stage1a.md
9d813bd3d8e54202641ec475e3c56f725b759357278a12a7bb8d2ab6cb97ed3e  docs/PLAN.md
```
Правило: перед приёмкой этапа хеш гейта пересчитывается. Расхождение → гейт
восстанавливается (`git checkout -- acceptance/`), работа агента пересматривается.

**Спорные моменты и принятые решения (до старта кода):**

1. **Разбиение Этапа 1 на два прогона (1A/1B).** В ТЗ Этап 1 — это «фундамент + TUI».
   Один прогон AGY такой объём не тянет (≈300 строк / 4 мин на файл — проверенный
   предел). Решение: 1A — каркас/конфиг/БД/модели/миграции/тесты; 1B — Textual.
   Плюс: ошибки схемы ловятся до UI.

2. **Сеть как связь, а не атрибут.** ТЗ говорит «сеть или список сетей» и «адрес не
   уникален глобально». Решение: `Wallet` без `network_id`, связь через
   `WalletNetwork(wallet_id, network_id)` + уникальность `Wallet(address, chain_type)`.
   Позволяет один EVM-адрес на Ethereum/Arbitrum/Base без дублей сущности.

3. **`address_raw` vs `address`.** Для EVM нормализуем в lowercase (сравнение/дедуп),
   исходное написание (EIP-55 checksum) храним в `address_raw` для отображения.
   Валидация checksum — Этап 2.

4. **Все 22 сущности §8 — сразу в 1A.** Спека требует «базовые модели»; вынесение
   остальных на потом означало бы миграцию схемы почти на каждом этапе. Цена — один
   большой `models.py`; выгода — следующие этапы не трогают миграции (кроме добавлений).

5. **Удаление группы не удаляет кошельки.** FK `ON DELETE SET NULL` +
   сервисный метод `delete_reassigning_wallets` (перенос в родителя/Unassigned).
   На уровне БД это не гарантируется — гарантируется тестом.

6. **Деньги только `Numeric(38,18)` или целые raw-единицы.** `Float` запрещён, гейт
   проверяет отсутствие FLOAT-колонок в полях balance/amount/value/price.

7. **Секреты.** В `config.yaml` только имена env-переменных (`api_key_env`). Гейт
   сканирует yaml на литеральные ключи; логирование обязано маскировать значения.

8. **`pytest` в dev-группе, не глобально.** Хост без глобального pytest, ставить
   пакеты в системный Python не будем — всё через `uv`.

9. **Критерии приёмки — свои (A1–A12 в PLAN.md).** ТЗ §12 — 16 пунктов MVP; я свёл их
   к 12 проверяемым, добавив слой провайдеров с явным `unsupported`, дедуп по
   `(network, tx_hash, log_index)`, обязательное разделение `confirmed|inferred`.

**Открытые вопросы (решаем по ходу):**

- Q1. Какой explorer API брать первым — Etherscan v2 (мультичейн, но ключ и квоты) или
  Blockscout (без ключа, но не все сети)? Решение при старте Этапа 3, после проверки
  актуальных лимитов.
- Q2. Инкрементальная синхронизация: курсор по номеру блока или по `page/offset`
  провайдера? Зависит от ответа Q1.
- Q3. Формат TUI-тестов: `App.run_test()` требует `pytest-asyncio`; проверить
  совместимость с Textual на Python 3.14 (иначе пин 3.12).
- Q4. Хранить ли сырые ответы провайдеров (аудит/дедуп) — рос. объём БД. Пока: нет,
  только нормализованные записи + курсоры.

---

## 2026-11-04 17:58 — Этап 1A передан в AGY

Запуск: `agy --mode accept-edits --print-timeout 25m --output-format json -p "<указатель
на tasks/stage1a.md>"` в `~/Projects/wallet-intelligence`, в фоне.
Ожидаемо: pyproject + config + 22 модели + session/repository + alembic + logging + тесты.

**Первый прогон провалился (42 с, 52k токенов, 0 файлов):**
```
jetski: no output produced — a tool required the "command" permission that headless
mode cannot prompt for, so it was auto-denied. Add an allow-rule under permissions.allow
in settings.json (e.g. command(<target>)). Alternatively, re-run with
--dangerously-skip-permissions to auto-approve all tools.
{"status":"SUCCESS", "response":"", "denied_actions":[{"action":"command","display_name":"RunCommand"}]}
```
Вывод: headless-режим AGY не умеет спрашивать разрешения. `status=SUCCESS` при пустом
ответе — ровно тот случай, когда конверт врёт: работа не сделана, а статус зелёный.
Поэтому правило «судить по артефакту» здесь сработало сразу: файлов на диске не было.

**Решение (спорный момент №10): права выданы на одну сессию, без правки конфига.**
Вместо `--dangerously-skip-permissions` (полный автопруф всех инструментов) и вместо
правки `~/.gemini/antigravity-cli/settings.json` использован флаг `--settings` —
сессионный JSON с точечным allow-списком: `uv`, `.venv/bin/python|pytest|ruff|alembic`,
`python`, `pytest`, `alembic`, git-чтение/коммит, базовые ФС-команды (`mkdir/cp/mv/ls/cat/wc/find/touch/chmod`).
`rm` и sudo намеренно не выданы. Проверено пробой: `--settings '{"permissions":{"allow":["command(echo)"]}}'`
→ агент реально выполнил `echo PERMS_OK` (14 с). Конфиг пользователя не изменён.

---

## 2026-11-04 18:24 — Этап 1A: прогон завершён, приёмка Hermes

**Прогон:** 1313 с (22 мин), 1 ход, 387k токенов (из них 8.5M cache-read), `status=SUCCESS`,
`denied_actions` нет. Ответ агента — отчёт на русском с таблицей файлов и выводами команд.

**Проверено лично (не по словам агента):**

| Проверка | Команда | Результат |
|---|---|---|
| хеш гейта не изменён | `sha256sum acceptance/gate_stage1a.py` | `b1f6d227…934b` = пин |
| тесты агента | `.venv/bin/python -m pytest -q` | `21 passed in 10.67s` |
| независимый гейт v1 | `.venv/bin/python -m pytest acceptance/gate_stage1a.py -q` | `13 passed` |
| линтер | `.venv/bin/ruff check .` | `All checks passed!` |
| `main.py --version` | `.venv/bin/python main.py --version` | `Wallet Intelligence Tracker 0.1.0` |
| `main.py` без аргументов | `.venv/bin/python main.py` | создал БД, миграция 001 применилась, сообщение «TUI (Stage 1B) не реализован», exit 0 |
| миграция с нуля | `WIT_DB_PATH=/tmp/wit_fresh.db alembic upgrade head` | `Running upgrade -> 001_initial_schema`, 23 таблицы (22 модели + alembic_version) |

**Что сделано агентом:** `pyproject.toml` + `uv.lock` (Python 3.12 запинен через
`.python-version`, venv 82 МБ), `config.yaml`, `.env.example`, `.gitignore`, `README.md`,
`main.py`, `app/config.py` (97), `app/database/models.py` (636, 23 класса), `session.py`,
`repository.py` (167), `app/utils/logging.py` (116, маскирование), `migrations/`,
`tests/unit` 5 файлов + `tests/integration` (миграции).

**Найдено моим ревью (гейт v1 был слишком мягким — это урок для следующих этапов):**

1. **B1 — «миграция» фиктивная:** ревизия `001_initial_schema` = 30 строк,
   внутри `Base.metadata.create_all(op.get_bind())`. Это не DDL, а `create_all` под видом
   ревизии: история не воспроизводима, autogenerate не увидит diff, downgrade бессмыслен.
2. **B2 — нормализация адреса только в `__init__`:** присваивание `w.address = "0xAB…"`
   оставляет uppercase → гарантия дедупа `(address, chain_type)` держится на дисциплине
   вызывающего кода.
3. **H1 — `init_db` глушит ошибки:** `except (ImportError, OSError, Exception)` → любая
   ошибка миграции молча подменяется `create_all`; плюс побочный эффект
   `os.environ["WIT_DB_PATH"] = …`; повторный `init_db` не делает `dispose()` старого engine.
4. **H2 — `WalletRepository.update()`** использует `hasattr` как белый список → можно
   переписать `id`, `created_at`, `address_raw`.

**Урок:** гейт должен проверять *качество артефакта*, а не только его наличие. Проверка
«таблицы существуют» пропустила фиктивную миграцию. Добавлены три проверки в гейт v2.

**Гейт v2 (16 проверок), новый пин:**
```
sha256  acceptance/gate_stage1a.py   (v2)
```
Добавлено: `test_migration_contains_real_ddl` (>=20 `op.create_table`, запрет `create_all`
и импорта живых моделей), `test_address_normalized_on_attribute_assignment`,
`test_init_db_is_idempotent`. Прогон v2 на текущем коде: `2 failed, 14 passed` —
ровно B1 и B2, ложных срабатываний нет.

**Итерация:** заведён `tasks/stage1a_fix.md` (B1, B2, H1, H2 + Definition of Done),
запущен второй прогон AGY в том же каталоге (сессионные права те же).

---

## 2026-11-04 18:48 — Второй прогон: частичный успех, упёрлись в права

**Результат:** 501 с, `status=SUCCESS`, `response=""`, 0 файлов итогового отчёта,
`denied_actions: [{action: command}]` — третий раз та же ловушка «зелёный конверт при
невыполненной работе».

**Что успело сделаться (проверено на диске и тестами):** B2 (валидаторы адресов на
`Wallet`/`ProjectContract`/`Token`), H1 (session.py без мутации env, узкий `except`,
`dispose()`), H2 (белый список полей в `update`). Автотесты: `25 passed, 2 failed` —
падения ровно там, где работа не закончена.

**Причина блокировки (найдена в `steps` конверсации AGY, sqlite-таблица `steps`):**
```
mv migrations/versions/001_initial_schema.py /tmp/001_backup.py && rm -f /tmp/scratch_generate.db
  && WIT_DB_PATH=/tmp/scratch_generate.db uv run alembic revision --autogenerate -m "tmp"
```
Запрещённой оказалась часть `rm`. Проверено пробами:
- `command(echo)` + `echo A && echo B` → **разрешено** (составные команды матчатся по частям);
- `command(rm -f /tmp)` + `rm -f /tmp/permprobe.txt` → **отказано** (правило матчится как
  префикс по границе токена; `/tmp/permprobe.txt` не начинается с `/tmp` + пробел).

**Вывод — правила для будущих прогонов:**
1. Allow-правило = префикс командной строки по границе токена. `command(uv)` покрывает
   `uv run …`, но `command(rm -f /tmp)` не покрывает `rm -f /tmp/x.txt`. Нужен `command(rm)`.
2. `rm` намеренно не давали в первом прогоне — и именно он остановил работу на 8-й минуте.
   В третьем прогоне добавлен `command(rm)`, а в задание — запрет удалять что-либо вне
   проекта и `/tmp` и требование удалять файлы через `python -c "os.remove(...)"`.
3. Хуже: агент склеивает `VAR=value cmd` и `cmd1 && cmd2 && cmd3`. Даже с разрешёнными
   частями такие строки рискованны — в задание добавлен «run protocol»: одна команда на
   вызов, без `&&`, без env-префиксов.
4. `status=SUCCESS` + пустой `response` + `denied_actions` — единственный надёжный признак
   «прогон умер на правах». Проверять это до чтения отчёта.

**Также найдено:** `test_session_init_and_context_manager` проходит в одиночку и падает в
полном прогоне → глобальный `_engine`/`_session_factory` в `session.py` течёт между тестами.
Заведён B3 (явная фабрика сессий) в `tasks/stage1a_fix2.md`.

**Третий прогон запущен** (те же права + `command(rm)`, «run protocol» в задании).

---

## 2026-11-04 19:20 — Права: полный разбор и решение

Четвёртая осечка: `denied_actions: [write_file]`. Т.е. `--mode accept-edits` разрешает
правку существующих файлов, но **создание новых** требует отдельного `write_file(<path>)`.
Итоговый набор для сессий AGY, проверенный пробами:

```
--settings '{"permissions":{"allow":["command(*)","write_file(/)","read_file(/)"]}}'
```

- `command(*)` — wildcard работает (проверено на `git grep`); `command(rm -f /tmp)` — нет.
- `write_file(/)` — создание/запись файлов (проверено: создал `probe_write.txt`).
- Конфиг пользователя (`~/.gemini/antigravity-cli/settings.json`) не изменён, всё сессионно.
- Решение о wildcard согласовано с пользователем явно (иначе 4-я итерация прав).

**Цена этих итераций:** прогоны 2–4 сгорели на правах (52k + 343k + 174k + 111k токенов),
из них полезной работы — примерно один. Урок на будущее: первым делом выдавать
`command(*)` + `write_file(/)` + `read_file(/)`, а не собирать allow-список по крупицам.

---

## 2026-11-04 19:40 — Этап 1A принят (после двух итераций правок)

**Прогон 5:** 884 с, `status=SUCCESS`, `denied_actions` нет, отчёт получен.

**Проверено лично:**

| Проверка | Результат |
|---|---|
| хеши гейтов | `90fabc93…` (1A v2) и `cfb29608…` (1B) — совпадают с пинами |
| тесты проекта | `30 passed in 10.84s` |
| гейт 1A v2 | `16 passed in 15.35s` |
| ruff | `All checks passed!` |
| миграция вверх/вниз/вверх | 23 таблицы → только `alembic_version` → 23 таблицы |
| DDL в ревизии | 22 × `op.create_table` + 6 × `op.create_index`, 402 строки; `create_all` и импорта живых моделей нет |
| изоляция тестов | полный прогон, обратный порядок файлов, каждый файл отдельно — зелено |

**Ложная тревога в моём же прогоне:** `2 failed` в `test_config` — из-за экспортированной
мной `WIT_DB_PATH` (Hermes-терминал держит env между вызовами). После `unset` — 30 passed.
Правило: гонять гейты с чистым env (`env -u WIT_DB_PATH` или `unset` в той же команде).

**Итог 1A:** каркас, конфиг (yaml+env), 22 модели с FK/unique/индексами/`Numeric(38,18)`,
реальная Alembic-ревизия с рабочим downgrade, репозитории с белым списком полей,
логирование с маскированием, 30 тестов. Этап принят.

---

## 2026-11-04 20:05 — Этап 1B принят (TUI-оболочка)

**Прогон:** 1943 с (32 мин), 1 ход, `status=SUCCESS`, `denied_actions` нет.

**Проверено лично:**

| Проверка | Результат |
|---|---|
| хеши гейтов | `90fabc93…` / `cfb29608…` — без изменений |
| тесты проекта | `43 passed in 96.48s` |
| гейт 1A | `16 passed` |
| гейт 1B | `9 passed in 85.70s` |
| ruff | `All checks passed!` |
| PTY-смоук (`script -qec python main.py`) | процесс живёт до таймаута, traceback нет (exit 124) |
| реальный рендер | `App.export_screenshot()` → SVG 56 КБ → PNG, просмотрено глазами (vision) |

**Что видно на реальном экране (dashboard 110×30):** верхняя строка «Wallet Intelligence
Tracker» + `Sync: ● Idle | Last update: Never`; сайдбар `SECTIONS` с 9 разделами и
подсветкой активного; заголовок `🏛 Dashboard`, описание и **реальные счётчики из БД**
(Wallets 0, Groups 0, Projects 0, Activities 0, Networks Enabled 7); нижняя строка хоткеев.
Экран Wallets: заголовок, описание, заглушка «Wallet Group Hierarchy — Coming in Stage 2»,
активный пункт меню.

**Мелкие дефекты (не блокеры, перенесены в Этап 2):**
1. нижняя строка хоткеев обрезается на 110 колонках (`q Qu…`) — нужен компактный вариант
   при узком окне;
2. длинные описания в экранах не переносятся, а режутся справа (`…balance insp`);
3. на экране Wallets нет человеческого empty state («кошельков пока нет + A добавить») —
   вместо него заглушка про этап 2; уйдёт вместе с реализацией CRUD.

**Артефакты:** `runs/shots/stage1b_dashboard.png`, `runs/shots/stage1b_wallets.png`.

**Итог 1B:** `app/application.py` (212 строк), `app/state.py`, 9 экранов, 4 виджета,
`app.tcss`, 5 UI-тестов; `main.py` запускает TUI. Всего в проекте 26 python-файлов,
616 строк UI-слоя. Этап принят.

---

## 2026-11-04 21:10 — Этапы 2A и 2B приняты

### 2A (бизнес-слой)

Прогон 1565 с, `SUCCESS`, отказов нет. Проверено мной: тесты `65 passed`, гейт 2A
`9 passed`, регрессия гейтов 1A+1B `25 passed`, ruff чист, миграция 001→002→base→002
(24 таблицы, `wallet_audit_log` на месте).

Файлы: `app/utils/validators.py` (164), `app/core/group_manager.py` (155),
`app/core/wallet_manager.py` (264), `app/core/import_manager.py` (419),
`app/core/network_manager.py` (65), миграция `002_wallet_audit_log.py` (44).

### 2B (UI-обвязка)

Прогон 1472 с, `SUCCESS`, отказов нет. Проверено мной: тесты `83 passed`, гейт 2B
`7 passed`, регрессия 1A+1B+2A `34 passed`, ruff чист, хеши всех четырёх гейтов
совпадают с пинами.

Файлы: `app/ui/screens/wallets.py` (409), `import_wallets.py` (234),
`wallet_form.py` (211) + модали групп.

**Визуальная проверка (скриншоты через `export_screenshot` → PNG → просмотр):**
- Wallets: дерево групп с вложенностью (COLD STORAGE → Main Cold, EXCHANGES → Binance/OKX,
  FARM WALLETS → Farm #1/#2, Unassigned), таблица `Name | Address | Group | Tags`,
  строка поиска, подсказка «Enter — детали».
- Панель деталей (Enter): `Wallet 002 … Group: Farm #1, Notes: touched by gate,
  Audit History: [2026-11-04 17:06:56] notes: None → touched by gate` — аудит реально
  отображается и читается.
- Футер хоткеев больше не обрезается на 140 колонках (дефект 1B закрыт).

**Осталось из косметики:** на 140 колонках правая колонка таблицы сжата до одной буквы
(`N` вместо `Networks`) — есть горизонтальный скролл, но заголовок нечитаем. Кандидат в
фикс Этапа 3 (вместе с колонкой статуса синхронизации).

**Артефакты:** `runs/shots/stage2b_wallets.png`, `runs/shots/stage2b_history.png`.

**MVP-статус по критериям PLAN.md:** A1 ✅, A2 ✅, A3 ✅, A4 ✅, A5 ✅ (импорт CSV/TXT/JSON
с превью, дедупом, отчётом, воркером), A10 ✅ (83 теста), A11 ✅, A12 ✅ (секретов нет).
Осталось для MVP: A6–A9 (провайдеры, синхронизация, активности, проекты) — этапы 3–5.






