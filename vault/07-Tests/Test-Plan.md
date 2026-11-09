---
doc: test-plan
updated: 2026-11-09
scope: ["e2e", "integration", "unit"]
---

# Test-Plan — wallet-intelligence

## Уровни тестов
| Уровень | Что проверяет | Где |
|---|---|---|
| unit | модули, pure-логика | `tests/unit/` |
| integration | БД, миграции, провайдеры | `tests/integration/` |
| e2e | сценарии пользователя (Textual headless) | `tests/e2e/` |

## Тест-кейсы
| TC | Тип | Prio | Сценарий | Статус | Связи |
|---|---|---|---|---|---|
| TC-001 | e2e | P1 | Запуск приложения → навигация по 9 разделам | passing | [[RUN-20261109-002]] |
| [[TC-002]] | e2e | P2 | Добавление кошелька → возврат на Dashboard → кошелёк виден | passing | [[RUN-20261109-002]] / [[FIX-001]] |
| [[TC-003]] | e2e | P3 | Пустые состояния: чистая БД без кошельков → #panel-wallets ('No wallets tracked yet') | passing | [[RUN-20261109-002]] |
| TC-004 | e2e | P2 | Добавление кошелька через UI-форму (отказ при пустом адресе) | passing | [[RUN-20261109-003]] |
| TC-005 | e2e | P2 | Поиск в Wallets фильтрует таблицу | passing | [[RUN-20261109-003]] |
| TC-006 | e2e | P2 | Импорт: preview → apply создаёт кошельки | passing | [[RUN-20261109-003]] |
| TC-007 | e2e | P2 | Редактирование кошелька через форму меняет имя | passing | [[RUN-20261109-004]] |
| TC-008 | e2e | P2 | Архивация кошелька (archived=True) | passing | [[RUN-20261109-004]] |
| TC-009 | e2e | P2 | Экраны Activities/Projects/Graph с данными | passing | [[RUN-20261109-004]] |

## Как составлять тест-кейсы
- Скилл `test-case-design`: техники (эквивалентные классы, граничные значения, таблица решений, pairwise, state transition), приоритеты P1–P3, трассировка `REQ → TC → RUN`.
- Шаблон: `vault/_templates/TestCase.md`. Детальный TC — отдельным файлом `07-Tests/TC-NNN.md`.
- Тестовые данные — скилл `test-data` + `tests/fixtures/factories.py` (`make_wallet(...)`), изоляция через `tests/e2e/conftest.py::clean_db`.

## Прогоны
- [[RUN-20261109-001]] (e2e, failed)

## Саммари (RU)
Заведена структура тест-кейсов: сводная таблица + шаблон + скиллы проектирования и тестовых данных.
E2E-сценарий TC-002 автоматизирован и падает из-за [[BUG-001]] (в бэклоге).

## Выводы (RU)
- Покрытие строится по трассировке REQ → TC → RUN; приоритеты P1 (smoke) → P3 (edge).
- Тестовая база — фабрики в `tests/fixtures/` и изолированная БД через `clean_db`.
