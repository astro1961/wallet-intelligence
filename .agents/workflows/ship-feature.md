---
description: Полный цикл фичи — код, CI, E2E, баги, фикс, гейт (CI-only, без деплоя)
---

# /ship-feature

Вход: описание фичи. Состояние — в `vault/02-Plan/STAGE-NN.md` и `vault/03-Logs/`.

1. **[developer]** Реализовать фичу в ветке `feature/<name>` + unit-тесты. Прогнать `ruff check .` и `pytest -m "not live"`.
2. **[CI]** Открыть PR, дождаться зелёного `ci.yml` (`gh pr checks --watch`). Красный → вернуть developer.
3. **[qa-engineer]** Прогнать E2E `pytest tests/e2e -q`, при необходимости дописать сценарии. Записать `vault/07-Tests/RUN-YYYYMMDD-NNN.md`.
4. **Дефекты severity ≥ major**:
   a. qa-engineer заводит `vault/04-Bugs/BUG-NNN.md` + `gh issue create`;
   b. `fix_iteration += 1`; если > 3 — **эскалация человеку, стоп**;
   c. **[developer]** фиксит причину, PR `Fixes #N`;
   d. вернуться к шагу 2.
5. **Quality gate:** все тесты зелёные, нет открытых blocker/critical/major; minor ≤ 5.
6. **Merge** (auto, после зелёных гейтов). Деплой в этой конфигурации отсутствует (CI-only).
7. Итоговый отчёт: что сделано, итерации, баги, ссылки на RUN.

## Правила
- QA не правит продуктовый код; developer не закрывает баги.
- Не пропускать гейт, не ставить `skip` вместо фикса.
