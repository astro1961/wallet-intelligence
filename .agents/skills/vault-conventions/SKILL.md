---
name: vault-conventions
description: Правила документации vault/ — ID-схема, статусы, связи, машиночитаемый frontmatter и обязательные русские блоки Саммари/Выводы. Использовать при создании или обновлении любого документа в vault.
---

# Vault conventions

## Структура
```
vault/
├── 00-Home.md            # навигация, текущий этап, открытые баги
├── 00-Conventions.md     # правила ID/статусов/связей
├── 01-Requirements/      # REQ-NNN
├── 02-Plan/              # STAGE-NN
├── 03-Logs/              # LOG-STAGE-NN (append-only)
├── 04-Bugs/              # BUG-NNN + Bugs-Dashboard
├── 05-Fixes/             # FIX-NNN + Fixes-Dashboard
├── 06-Notes/             # NOTE-NNN, ADR-NNNN
├── 07-Tests/             # Test-Plan, RUN-YYYYMMDD-NNN, attachments/
└── _templates/           # Requirement, Stage, Log, Bug, Fix, ADR, Note, Run
```

## Формат любого документа
1. **YAML frontmatter** — машиночитаемые поля (`id`, `status`, даты, связи). Поля не удалять.
2. **Тело** — строго по шаблону из `_templates/`.
3. **В конце — обязательные русские блоки** (для человеческого контроля):
   ```markdown
   ## Саммари (RU)
   <2–4 предложения простым языком>

   ## Выводы (RU)
   - <пункт>
   ```

## ID и статусы
| Тип | Формат | Статусы |
|---|---|---|
| Requirement | REQ-NNN | draft → approved → implemented → verified |
| Stage | STAGE-NN | planned → in-progress → done → accepted |
| Bug | BUG-NNN | open → in-progress → fixed → verified → closed |
| Fix | FIX-NNN | draft → merged → verified → released |
| ADR | ADR-NNNN | proposed → accepted/rejected → superseded |
| Run | RUN-YYYYMMDD-NNN | passed / failed / error |

## Куда что писать
- Прогон тестов → `07-Tests/RUN-YYYYMMDD-NNN.md` (frontmatter: `status`, `total/passed/failed`, `failed_tests`).
- Найденный баг → `04-Bugs/BUG-NNN.md` (шаблон Bug).
- Фикс → `05-Fixes/FIX-NNN.md` + связь `bug: BUG-NNN`.
- Обновлять `00-Home.md` (текущий этап, `open_bugs`) после изменений.

## Правила
- Всегда копируй шаблон из `_templates/`, не изобретай формат.
- Даты — ISO (`YYYY-MM-DD`), время `YYYY-MM-DDTHH:MM`.
- `03-Logs/` — append-only.
- Баг закрывается только с доказательством (RUN зелёный + повторная проверка).
