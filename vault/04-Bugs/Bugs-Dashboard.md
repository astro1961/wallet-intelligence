```dataview
TABLE WITHOUT ID
  file.link AS "Баг",
  title AS "Кратко",
  severity AS "Severity",
  status AS "Статус",
  stage AS "Этап"
FROM "04-Bugs"
WHERE file.name != "Bugs-Dashboard"
SORT choice(severity, "S1", 1, "S2", 2, "S3", 3, "S4", 4, 9) ASC, file.name ASC
```

## Открытые (RU)
```dataview
TABLE WITHOUT ID file.link AS "Баг", title, severity, status
FROM "04-Bugs"
WHERE file.name != "Bugs-Dashboard" AND status != "closed"
SORT file.name ASC
```

## Саммари (RU)
Сводная таблица всех багов проекта. Severity: S1 (critical) → S4 (trivial).
Новые баги заводятся по шаблону `_templates/Bug.md` со связью `requirement: "[[REQ-NNN]]"`.

## Выводы (RU)
- Открытых багов без фикса и теста быть не должно: каждый баг → `[[FIX-NNN]]` и падающий тест.
