```dataview
TABLE WITHOUT ID
  file.link AS "Фикс",
  title AS "Кратко",
  bug AS "Баг",
  status AS "Статус",
  stage AS "Этап"
FROM "05-Fixes"
WHERE file.name != "Fixes-Dashboard"
SORT file.name ASC
```

## Ожидают проверки (RU)
```dataview
TABLE WITHOUT ID file.link AS "Фикс", title, bug, status
FROM "05-Fixes"
WHERE file.name != "Fixes-Dashboard" AND status != "released"
```

## Саммари (RU)
Сводная таблица фиксов. Каждый фикс связан с багом (`bug: "[[BUG-NNN]]"`) и проверкой (`verified_by: "[[RUN-...]]"`).

## Выводы (RU)
- Фикс закрывается только после зелёного прогона, отчёт которого лежит в `07-Tests/`.
