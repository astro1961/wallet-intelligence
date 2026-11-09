---
name: bug-triage
description: Оформление дефектов в vault (BUG-NNN) и GitHub Issues — шаблон, severity S1–S4, проверка дубликатов, доказательства. Использовать когда нужно завести баг после тестирования.
---

# Bug triage

## Severity (S1–S4)
- **S1** critical — блокер, потеря данных/доступа.
- **S2** major — ключевая функция не работает.
- **S3** minor — работает с обходом.
- **S4** trivial — косметика.

## 1. Сначала — vault (источник истины)
1. Поиск дубликатов: `grep -rl "<ключевые слова>" vault/04-Bugs/`.
2. Если дубликат — допиши evidence в существующий `BUG-NNN`, не заводи новый.
3. Нет дубликата — скопируй `vault/_templates/Bug.md` → `vault/04-Bugs/BUG-NNN.md`
   (ID = максимум + 1), заполни:
   - `severity: S1|S2|S3|S4`
   - `requirement: "[[REQ-NNN]]"`, `stage: "[[STAGE-NN]]"` (wiki-links!)
   - шаги, ожидание/факт, доказательства (скриншот в `07-Tests/attachments/`)
   - русские блоки **Саммари (RU)** и **Выводы (RU)**
4. Обнови `vault/00-Home.md` (open_bugs) и `[[Bugs-Dashboard]]`.
5. Допиши запись в `vault/03-Logs/LOG-STAGE-NN.md` со ссылкой `[[BUG-NNN]]`.

## 2. Затем — GitHub issue (внешний трекер)
1. Поиск дубликатов: `gh issue list --search "<keywords>" --label bug`.
2. Создание: `gh issue create --title "[BUG-NNN] <кратко>" --body "<описание + ссылка на vault>" --label bug,severity:s2,found-by:qa-agent`.
3. В теле — ссылка на `vault/04-Bugs/BUG-NNN.md` и на падающий тест.

## Правила
- Один баг — один `BUG-NNN` и один issue.
- Каждый баг сопровождается падающим тестом (`tests/e2e/` или `e2e/regression/`).
- Закрытие только с зелёным `[[RUN-...]]` и повторной проверкой.
- Severity — по влиянию на пользователя, не по усилию фикса.
