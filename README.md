# Day 12 Lab — Deployment: Đưa AI Agent Lên Cloud

> **Student Name:** Thái Thị Yến Nhi  
> **Student ID:** 2A202600783  
> **Lab:** Day 12 — Hạ tầng Cloud và Deployment

Repository này trước hết là **bài nộp Day 12 Lab**. Các exercise, mission answers, final lab source code, deployment report và screenshot evidence được giữ ở đúng vị trí mà rubric và instructor guide yêu cầu.

Repository đồng thời có một phần mở rộng độc lập là **MaiThuyLaw AI**. Phần mở rộng được tách hoàn toàn vào [`maithuylaw-ai/`](maithuylaw-ai/) để không thay thế hoặc làm mờ các deliverable của bài lab.

> **MaiThuyLaw AI production extension:** xem [`maithuylaw-ai/README.md`](maithuylaw-ai/README.md).

---

## Điều hướng chấm bài

| Deliverable | Vị trí |
|---|---|
| Nội dung và yêu cầu lab | [`CODE_LAB.md`](CODE_LAB.md) |
| Câu trả lời Part 1–6 | [`MISSION_ANSWERS.md`](MISSION_ANSWERS.md) |
| Checklist nộp bài | [`DAY12_DELIVERY_CHECKLIST.md`](DAY12_DELIVERY_CHECKLIST.md) |
| Hướng dẫn chấm | [`INSTRUCTOR_GUIDE.md`](INSTRUCTOR_GUIDE.md) |
| Deployment report | [`DEPLOYMENT.md`](DEPLOYMENT.md) |
| Screenshot evidence | [`screenshots/`](screenshots/) |
| Final lab source | [`app/`](app/) |
| Reference complete lab | [`06-lab-complete/`](06-lab-complete/) |
| Quick start | [`QUICK_START.md`](QUICK_START.md) |
| Troubleshooting | [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) |

## Rubric mapping

Theo instructor guide, điểm số gồm:

| Thành phần | Điểm | Bằng chứng |
|---|---:|---|
| Part 1–5: Exercises | 40 | `MISSION_ANSWERS.md` và các folder `01-` đến `05-` |
| Part 6: Final Project | 60 | Root final app, Docker/Redis config, deployment report và screenshots |
| **Tổng** | **100** | |

Part 6 được đối chiếu như sau:

| Nhóm tiêu chí | Điểm | Implementation |
|---|---:|---|
| Functionality | 20 | `/ask`, conversation history và error handling trong `app/` |
| Docker & Configuration | 15 | Root `Dockerfile`, `docker-compose.yml`, `.env.example` |
| Security | 20 | API key, rate limit, cost guard và environment-based secrets |
| Reliability | 15 | `/health`, `/ready`, lifespan startup/shutdown và Redis history |
| Deployment | 10 | `railway.toml`, `DEPLOYMENT.md` và screenshot evidence |

## Nội dung từng phần

| Part | Folder | Nội dung |
|---:|---|---|
| 1 | [`01-localhost-vs-production/`](01-localhost-vs-production/) | Dev vs production, 12-factor app, config và health checks |
| 2 | [`02-docker/`](02-docker/) | Docker basics, multi-stage build và Docker Compose |
| 3 | [`03-cloud-deployment/`](03-cloud-deployment/) | Railway, Render, Cloud Run và deployment workflow |
| 4 | [`04-api-gateway/`](04-api-gateway/) | API key, rate limiting và cost protection |
| 5 | [`05-scaling-reliability/`](05-scaling-reliability/) | Redis, stateless design, health/readiness và scaling |
| 6 | [`06-lab-complete/`](06-lab-complete/) | Reference implementation tổng hợp |

## Final lab application

Rubric-facing implementation nằm ở root:

```text
app/
├── main.py
├── config.py
├── auth.py
├── rate_limiter.py
├── cost_guard.py
└── ui.py

utils/mock_llm.py
Dockerfile
docker-compose.yml
requirements.txt
.env.example
railway.toml
```

Các endpoint chính:

| Method | Endpoint | Mục đích |
|---|---|---|
| `GET` | `/health` | Liveness và storage status |
| `GET` | `/ready` | Readiness check |
| `POST` | `/ask` | Protected agent endpoint |
| `GET` | `/history` | Conversation history theo user |
| `GET` | `/usage` | Monthly budget usage |

## Chạy final lab local

### Python

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export AGENT_API_KEY=local-dev-key
export REDIS_URL=redis://localhost:6379/0
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker Compose

```bash
docker compose up -d --build
docker compose ps
```

## Self-test nhanh

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Không có API key phải bị từ chối:

```bash
curl -i -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Hello"}'
```

Có API key phải thành công:

```bash
curl -i -X POST http://localhost:8000/ask \
  -H "X-API-Key: local-dev-key" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"lab-user","question":"Hello"}'
```

## Deployment evidence

Deployment report và bằng chứng của bài lab được giữ riêng tại:

- [`DEPLOYMENT.md`](DEPLOYMENT.md)
- [`screenshots/01-railway-deploy-success.png`](screenshots/01-railway-deploy-success.png)
- [`screenshots/02-public-health.png`](screenshots/02-public-health.png)
- [`screenshots/03-public-auth.png`](screenshots/03-public-auth.png)
- [`screenshots/04-public-ask-success.png`](screenshots/04-public-ask-success.png)
- [`screenshots/05-docker-compose-redis.png`](screenshots/05-docker-compose-redis.png)
- [`screenshots/06-rate-limit-429.png`](screenshots/06-rate-limit-429.png)

Public URL trong `DEPLOYMENT.md` là deployment evidence tại thời điểm hoàn thành lab. Deployment mới của MaiThuyLaw AI được quản lý độc lập trong thư mục product.

## Repository layout

```text
.
├── 01-localhost-vs-production/
├── 02-docker/
├── 03-cloud-deployment/
├── 04-api-gateway/
├── 05-scaling-reliability/
├── 06-lab-complete/
├── app/                         # Final lab app
├── utils/                       # Lab mock LLM
├── screenshots/                 # Lab evidence
├── maithuylaw-ai/               # Independent production extension
├── MISSION_ANSWERS.md
├── DEPLOYMENT.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── railway.toml
```

## MaiThuyLaw AI extension

MaiThuyLaw AI áp dụng các production concepts của Day 12 vào một domain application lớn hơn, nhưng có source code, dependencies, Dockerfile, tests và deployment configuration riêng.

- Product overview: [`maithuylaw-ai/README.md`](maithuylaw-ai/README.md)
- Technical docs: [`maithuylaw-ai/docs/`](maithuylaw-ai/docs/)
- Product deployment guide: [`maithuylaw-ai/docs/deployment.md`](maithuylaw-ai/docs/deployment.md)
