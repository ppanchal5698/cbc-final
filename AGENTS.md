# CBC Estimating Copilot (domain-bounded layout)

See docs/architecture.md. Shared domain: packages/cbc. Services under
services/{platform,intake,extraction,pricing,quoting,catalog}. Web: apps/web.
Data model: docs/collections.mongodb.md. Runtime: app_lifecycle.md.

Run: docker compose -f infra/docker-compose.yml up -d --build
