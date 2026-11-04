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



