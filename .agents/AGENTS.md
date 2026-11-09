---
scope: workspace
always: true
---

# Правила проекта — wallet-intelligence

## Роли (не совмещать в одном контексте)
- **developer** — пишет и правит продуктовый код, unit-тесты, открывает PR.
- **qa-engineer** — пишет E2E, гоняет тесты, заводит баги, ведёт vault. Продуктовый код не трогает.
- **critic** — независимое ревью кода/планов, вердикт APPROVE / REQUEST CHANGES / BLOCK.

## Работа
- Язык общения — русский; код, коммиты, имена — английский.
- Секреты только в `.env` (chmod 600), никогда в git/логах. `.env.example` без значений.
- Любое изменение кода сопровождается тестом (unit; для пользовательских сценариев — E2E в `tests/e2e/`).
- Ветки: `feature/<id>`, `fix/<issue>`. Merge — только после зелёного CI (`ruff check .`, `pytest -m "not live"`).
- Лимит итераций «баг → фикс → перепроверка» — **3**, затем эскалация человеку.

## Тесты
- unit — `tests/unit/`, integration — `tests/integration/`, E2E — `tests/e2e/` (Textual `App.run_test`, headless).
- Live-тесты (`-m live`) в CI не запускаются.

## Документация
- Ведётся в `vault/` по правилам `vault/00-Conventions.md` (Obsidian wiki-links, Dataview, `Саммари (RU)` / `Выводы (RU)`).
- История в `vault/03-Logs/` — append-only.
- Баг закрывается только с зелёным `RUN-...` и повторной проверкой.
