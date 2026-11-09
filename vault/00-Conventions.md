---
doc: conventions
version: 2
updated: 2026-11-08
applies_to: ["agents", "humans"]
---

# Conventions — правила vault

> Машиночитаемость: YAML-frontmatter (id, status, даты, связи wiki-links `[[...]]`).
> Человеческий контроль: в конце каждого документа — **Саммари (RU)** и **Выводы (RU)**.

## ID-схема
| Тип | Формат | Где лежит |
|---|---|---|
| Требование | `REQ-NNN` | `01-Requirements/REQ-NNN.md` |
| Этап | `STAGE-NN` | `02-Plan/STAGE-NN.md` |
| Журнал этапа | `LOG-STAGE-NN` | `03-Logs/LOG-STAGE-NN.md` (append-only) |
| Баг | `BUG-NNN` | `04-Bugs/BUG-NNN.md` |
| Фикс | `FIX-NNN` | `05-Fixes/FIX-NNN.md` |
| Решение | `ADR-NNNN` | `06-Notes/ADR-NNNN.md` |
| Заметка | `NOTE-NNN` | `06-Notes/NOTE-NNN.md` |
| Прогон тестов | `RUN-YYYYMMDD-NNN` | `07-Tests/RUN-YYYYMMDD-NNN.md` |
| Тест-кейс | `TC-NNN` | `07-Tests/Test-Plan.md` |

## Severity (S1–S4)
- **S1** — critical: блокер, потеря данных/доступа.
- **S2** — major: ключевая функция не работает.
- **S3** — minor: работает с обходом.
- **S4** — trivial: косметика.

## Статусы
- **Requirement**: `draft → approved → implemented → verified`
- **Stage**: `planned → in-progress → done → accepted`
- **Bug**: `open → in-progress → fixed → verified → closed`; `backlog` — отложен, не блокирует
- **Fix**: `draft → merged → verified → released`
- **Run**: `passed | failed | error`

## Связи — Obsidian wiki-links в frontmatter
```yaml
# BUG-007
requirement: "[[REQ-003]]"
stage: "[[STAGE-02]]"
fix: "[[FIX-005]]"

# FIX-005
bug: "[[BUG-007]]"
verified_by: "[[RUN-20261108-001]]"

# RUN-...
stage: "[[STAGE-02]]"
```

Цепочка: ТЗ → `[[REQ-...]]` → `[[STAGE-...]]` → `[[BUG-...]]` → `[[FIX-...]]` → журнал этапа.

## Обязательные блоки в конце документа
```markdown
## Саммари (RU)
<2–4 предложения простым языком>

## Выводы (RU)
- <пункт>
```

## Правила
1. ID = «максимум в папке + 1»; не переиспользуются.
2. Поля frontmatter не удалять; расширять можно.
3. Даты — ISO `YYYY-MM-DD`.
4. `03-Logs/` — append-only.
5. Баг закрывается только с зелёным `[[RUN-...]]` и повторной проверкой.
6. Битая ссылка `[[...]]` — дефект, чинится через workflow `/vault-init`.
