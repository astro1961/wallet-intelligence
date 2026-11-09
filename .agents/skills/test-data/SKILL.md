---
name: test-data
description: Тестовая база — фабрики, сиды, константы и изоляция тестовой БД. Использовать при подготовке данных для unit/E2E-тестов.
---

# Test data (тестовая база)

## Принципы
- **Изоляция**: своя БД на прогон (`/tmp/<name>_<pid>.db`), удалять перед стартом, чтобы миграции накатились с нуля.
- **Детерминизм**: фиксированные адреса/суммы/даты; `random` только с seed.
- **Никаких прод-данных**: синтетика и тестовые аккаунты.

## Слои
```
tests/fixtures/
├── data.py          # константы: адреса, суммы, ключи
├── factories.py     # фабрики: make_wallet(), make_group(), make_activity()
└── seeds.py         # базовые сети/проекты: seed_networks(session)
tests/e2e/conftest.py # фикстуры pytest: app, db, clean_db
```

## Пример фабрики
```python
# tests/fixtures/factories.py
from app.database.models import Wallet

def make_wallet(session, address="0x111122223333444455556667777888899990000a",
                name="TestWallet1", chain_type="evm"):
    w = Wallet(address=address, name=name, chain_type=chain_type)
    session.add(w)
    session.commit()
    return w
```

## Фикстура E2E
```python
# tests/e2e/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def clean_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    if db.exists():
        db.unlink()
    monkeypatch.setenv("WIT_DB_PATH", str(db))
    return db
```

## Правила
- Фабрики явно создают и возвращают объект, без скрытых зависимостей.
- Данные — в `tests/fixtures/`, не дублировать в каждом тесте.
- Для E2E: чистая БД + минимум сидов (только нужное сценарию).
- Скриншоты/артефакты — в `vault/07-Tests/attachments/`.
