## Repository root directory

This repository contains both the original Day 12 lab and the independent product extension. For the MaiThuyLaw AI Railway service, set the service **Root Directory** to:

```text
maithuylaw-ai
```

Railway will then use the product-local `Dockerfile`, `railway.toml`, `.env.example` and source tree. The repository-root deployment files remain reserved for the lab deliverable.

# Deployment Guide

## Production services

A persistent deployment needs:

- the application container;
- Redis;
- a Gemini API key for LLM synthesis;
- a strong session secret;
- the public application origin.

## Railway variables

```text
ENVIRONMENT=production
GEMINI_API_KEY=<secret>
GEMINI_MODEL=gemini-3.1-flash-lite
MAITHUYLAW_SESSION_SECRET=<long-random-secret>
REDIS_URL=<Railway Redis URL>
MAITHUYLAW_ALLOWED_ORIGINS=https://<public-domain>
MAITHUYLAW_RATE_LIMIT_PER_MINUTE=10
MAITHUYLAW_DAILY_LIMIT=500
MONTHLY_BUDGET_USD=10
```

Optional restricted API mode:

```text
MAITHUYLAW_API_KEY=<secret>
```

Optional controlled search:

```text
MAITHUYLAW_REALTIME_ENABLED=true
TAVILY_API_KEY=<secret>
```

Do not expose a server secret in the frontend bundle.

## Build and readiness

Railway uses `Dockerfile` and `railway.toml`. The configured readiness endpoint is:

```text
/ready
```

`/health` reports process/storage status. `/ready` fails when required dataset startup validation fails.

## Local container test

```bash
docker build -t maithuylaw-ai .
docker run -d --name maithuylaw \
  -p 8000:8000 \
  --env-file .env.local \
  maithuylaw-ai

MAITHUYLAW_BASE_URL=http://127.0.0.1:8000 \
MAITHUYLAW_API_KEY=<configured-key-or-empty> \
python scripts/smoke_test_backend.py
```

## Post-deploy smoke test

```bash
MAITHUYLAW_BASE_URL=https://<railway-domain> \
MAITHUYLAW_API_KEY=<configured-key-or-empty> \
MAITHUYLAW_EXPECT_REDIS=true \
python scripts/smoke_test_backend.py
```

Acceptance:

- `/health` and `/ready` return `200`;
- legal Q&A returns controlled sources and valid citation metadata;
- unsafe and out-of-domain requests are refused;
- `/history` contains the created chat;
- `/usage` returns persistent counters;
- Redis is reported available when expected.
