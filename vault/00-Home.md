---
vault: wallet-intelligence
updated: 2026-11-09
current_stage: "[[STAGE-01]]"
open_bugs: 0
backlog_bugs: 0
verdict: "E2E зелёный (13/13)"
---

# Wallet Intelligence — Home

## Навигация
- [[00-Conventions]] · [[01-Requirements]] · [[02-Plan]] · [[03-Logs]] · [[04-Bugs]] · [[05-Fixes]] · [[06-Notes]] · [[07-Tests]]
- Дашборды: [[Bugs-Dashboard]] · [[Fixes-Dashboard]] · [[Test-Plan]]

## Текущий этап
- [[STAGE-01]] — **в работе (NO-GO по результатам E2E)**

## Открытые баги
```dataview
TABLE WITHOUT ID file.link AS "Баг", title, severity, status
FROM "04-Bugs"
WHERE status != "closed" AND file.name != "Bugs-Dashboard"
SORT file.name ASC
```

## Последние прогоны
```dataview
TABLE WITHOUT ID file.link AS "Прогон", type, status, passed, failed
FROM "07-Tests"
WHERE startswith(file.name, "RUN-")
SORT file.name DESC
LIMIT 5
```

## Саммари (RU)
Разработан и запущен E2E-тест пользовательского сценария добавления кошелька `tests/e2e/test_wallet_add_flow.py`. Выявлен баг [[BUG-001]] (S2 major): при переключении обратно на Dashboard панель `#panel-wallets` не обновляет список кошельков. Прогон [[RUN-20261109-001]] завершился со статусом `failed`. Вынесен вердикт **NO-GO**.

## Выводы (RU)
- Открыт 1 дефект: [[BUG-001]] (S2).
- Продуктовый код не изменялся в соответствии с ограничениями роли QA.
- Требуется исправление разработчиком (добавление `on_screen_resume` в `DashboardScreen`) и повторный прогон E2E.
