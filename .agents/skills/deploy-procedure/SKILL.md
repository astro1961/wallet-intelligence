---
name: deploy-procedure
description: Процедура развёртывания приложения — staging/production, проверки перед деплоем, smoke, откат. Использовать когда нужно выкатить готовый код.
---

# Deploy procedure

## Перед деплоем (обязательно)
1. Все тесты зелёные (unit + E2E).
2. CI зелёный (`gh pr checks` / `gh run list`).
3. Есть GO-вердикт от qa-engineer.
4. Секреты — в env/секрет-хранилище, не в коде.
5. Есть план отката (предыдущий образ/тег/коммит).

## Staging
1. Деплой: `./scripts/deploy.sh staging` (или хостинг-специфичная команда).
2. Дождись healthcheck: `curl -f <STAGING_URL>/health` (или `/healthz`).
3. Smoke: `./scripts/smoke.sh staging`.
4. Smoke упал → откат → возврат к qa-engineer.

## Production
1. Только после зелёного staging.
2. Деплой: `./scripts/deploy.sh production`.
3. Healthcheck + `./scripts/smoke.sh production`.
4. Провал → автоматический откат (`./scripts/rollback.sh`).

## Адаптация под стек
- **Python/Docker**: `docker compose build && docker compose up -d`, healthcheck `/healthz`, откат — предыдущий тег образа.
- **Node/Vercel/Netlify**: `vercel deploy --prod`, откат `vercel rollback`.
- **Python-пакет/CLI**: сборка (`uv build`), тег версии, публикация; откат — предыдущая версия.
- **Статический TUI**: тег + публикация артефакта.

## Правила
- Не деплоить с красным CI.
- Не деплоить в прод без ручного апрува (на старте).
- Логировать версию/commit, который выкатили.
- Всегда проверять healthcheck после деплоя.
