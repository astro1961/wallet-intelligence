---
name: e2e-testing
description: Сквозное и исследовательское тестирование — E2E-сценарии пользователя (Textual headless для TUI, Playwright для веба), сбор доказательств и фиксация в vault. Использовать при проверке фичи, воспроизведении бага и перепроверке фикса.
---

# E2E-тестирование

## Когда использовать
- Проверка фичи на стенде/в приложении глазами пользователя
- Воспроизведение бага и сбор доказательств
- Перепроверка фикса

## Уровни (важно: E2E ≠ unit)
- **unit** — модули и pure-логика (`tests/unit/`), быстрые, без UI.
- **integration** — БД, миграции, внешние провайдеры (`tests/integration/`).
- **E2E** — полный сценарий пользователя через реальный UI:
  - **TUI (Textual):** `tests/e2e/` на `App.run_test(size=(W,H))` — headless: запуск, навигация,
    ввод, проверка виджетов (`query_one`), отсутствие исключений.
  - **Web:** Playwright (`e2e/`), `getByRole`/`getByTestId`, baseURL из `E2E_BASE_URL`.

Для wallet-intelligence (Textual) E2E-тесты пишутся в `tests/e2e/` и запускаются:
```bash
.venv/bin/python -m pytest tests/e2e -q
```

## Процедура
1. Прочитай требование/этап (`vault/01-Requirements/`, `vault/02-Plan/`), выпиши критерии приёмки.
2. Для каждого критерия — тест-кейс (`TC-NNN` в `vault/07-Tests/Test-Plan.md`).
3. Напиши E2E-сценарий (happy path + негатив/край).
4. Прогони E2E, затем unit/integration как регресс.
5. Зафиксируй прогон в `vault/07-Tests/RUN-YYYYMMDD-NNN.md` (см. `skills/vault-conventions`).
6. Найденный баг → `vault/04-Bugs/BUG-NNN.md`; обнови `vault/00-Home.md`.

## Пример E2E для Textual
```python
import asyncio
from app.application import WalletTrackerApp

async def test_dashboard_shows_added_wallet():
    app = WalletTrackerApp()
    async with app.run_test(size=(120, 40)) as pilot:
        app.nav_to("dashboard")
        await pilot.pause()
        # добавить кошелёк в БД (или через UI-форму) …
        app.nav_to("wallets"); app.nav_to("dashboard")
        await pilot.pause()
        assert "0xNEW…" in str(app.screen.query_one("#panel-wallets").render())
```

## Правила
- Не используй продовые данные и реальные аккаунты; тестовая БД (`WIT_DB_PATH=/tmp/...`).
- Селекторы — по `id`/`role`, не по позиции.
- Не помечай баг исправленным без зелёного E2E и повторной проверки.
- Отчёт всегда с русскими блоками **Саммари (RU)** и **Выводы (RU)**.

## Формат отчёта
Сводка (pass/fail по сценариям) → баги с severity → ссылки на `vault/07-Tests/RUN-...`.
