# Smart API Gateway — Phase 1: Core Reverse Proxy

A production-grade API gateway built with FastAPI. Sits between clients and backend services, routing traffic, forwarding requests, and logging every transaction.

```
Client → Gateway (:8000) ─┬→ Auth Service  (:9001)
                           ├→ Chat Service  (:9002)
                           └→ AI Service    (:9003)
```

---

## What You'll Learn

| Concept | Where it lives |
|---|---|
| Reverse proxy / HTTP lifecycle | `gateway/main.py` — catch-all route handler |
| Async networking (httpx) | `gateway/connection_pool.py` |
| Connection pooling | `ConnectionPoolManager` — one pool per service |
| Longest-prefix routing | `gateway/router.py` |
| Request tracing middleware | `request_tracing_middleware` in `main.py` |
| Structured logging | `gateway/logger.py` — ring buffer + stats |
| Pydantic settings / 12-factor config | `gateway/config.py` |
| FastAPI lifespan (startup/shutdown) | `lifespan()` in `main.py` |

---

## Project Structure

```
smart-api-gateway/
├── gateway/
│   ├── main.py            # FastAPI app, middleware, proxy handler
│   ├── router.py          # Longest-prefix route resolution
│   ├── connection_pool.py # httpx pool manager (one client per service)
│   ├── logger.py          # Structured logger with ring buffer
│   └── config.py          # Pydantic settings (env-var driven)
├── services/
│   ├── auth_service/      # Mock auth backend  (:9001)
│   ├── chat_service/      # Mock chat backend  (:9002)
│   └── ai_service/        # Mock AI backend    (:9003)
├── tests/
│   └── test_gateway.py    # 16 unit + integration tests
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── requirements.txt
└── run_local.sh           # One-command local start
```

---

## Quick Start (Local)

```bash
# 1. Install deps
pip install -r requirements.txt

# 2. Start everything (gateway + 3 mock services)
bash run_local.sh
```

Then try it:

```bash
# Gateway health
curl http://localhost:8000/health

# See the routing table
curl http://localhost:8000/gateway/routes

# Hit the auth service through the gateway
curl http://localhost:8000/auth/health
curl -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"secret"}'

# Hit the chat service
curl http://localhost:8000/chat/rooms

# Hit the AI service
curl http://localhost:8000/ai/models
curl -X POST http://localhost:8000/ai/complete \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"What is a reverse proxy?"}'

# Unmapped path → 404 from gateway
curl http://localhost:8000/unknown/path
```

Every response includes:
- `X-Request-ID` — unique 8-char ID for tracing
- `X-Response-Time` — gateway latency in ms
- `X-Gateway-Service` — which upstream handled it (visible to upstream)

---

## Run Tests

```bash
pytest tests/ -v
```

16 tests covering:
- Router: prefix resolution, longest-prefix-wins, dynamic routes, edge cases
- Integration: health, routing table, 404s, tracing headers
- Logger: buffering, stats aggregation

---

## Docker

```bash
cd docker
docker-compose up --build
```

---

## Configuration

All config via environment variables (or `.env` file):

| Variable | Default | Description |
|---|---|---|
| `AUTH_SERVICE_URL` | `http://localhost:9001` | Auth upstream base URL |
| `CHAT_SERVICE_URL` | `http://localhost:9002` | Chat upstream base URL |
| `AI_SERVICE_URL` | `http://localhost:9003` | AI upstream base URL |
| `POOL_MAX_CONNECTIONS` | `100` | Max sockets per service pool |
| `POOL_MAX_KEEPALIVE` | `20` | Warm idle connections per pool |
| `REQUEST_TIMEOUT` | `30.0` | Upstream timeout (seconds) |
| `CONNECT_TIMEOUT` | `5.0` | TCP connect timeout (seconds) |

---

## How the Proxy Works (Step by Step)

```
1. Request arrives at gateway

2. request_tracing_middleware fires:
   - Generates X-Request-ID
   - Records start time

3. Route matching (GatewayRouter.resolve):
   - Longest-prefix match on URL path
   - /auth/me → auth service
   - /chat/rooms/1 → chat service
   - /unknown → no match → 404

4. Connection pool lookup:
   - pool_manager.get_client("auth")
   - Returns persistent httpx.AsyncClient
   - Reuses existing TCP connections (keepalive)

5. Forward request:
   - Copies method, headers, body
   - Strips hop-by-hop headers (Connection, Transfer-Encoding...)
   - Adds X-Forwarded-For, X-Gateway-Service headers

6. Receive upstream response, stream back to client

7. Log the transaction (request ID, latency, status, service)
```

---

## Phase 2 Roadmap

- Rate limiting (Redis token bucket)
- Retry with exponential backoff + circuit breaker
- PostgreSQL request log persistence
- AI request classification (route by intent, not just prefix)
- Health-check aware load balancing across multiple instances
- Admin dashboard (log viewer, live traffic stats)
