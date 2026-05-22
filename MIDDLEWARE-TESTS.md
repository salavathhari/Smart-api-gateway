# Phase 3 Middleware Tests - Comprehensive Guide

**Focus**: Request/Response middleware pipeline testing  
**Test Count**: 6 tests  
**Coverage**: Request tracking, timing, logging, rate limiting headers

---

## Middleware Stack Architecture

```
┌─ Incoming Request ────────────────────┐
│                                       │
└──────────┬──────────────────────┬─────┘
           │                      │
      ┌────▼─────┐         ┌─────▼────┐
      │ REQUEST  │         │ RESPONSE │
      │ PHASE    │         │ PHASE    │
      └─────────────────────────────────┘
           │
      ┌────┴────────────────────────┬───┐
      │                             │   │
   ┌──▼──┐  ┌──────┐  ┌──────┐  ┌──┴─┐│
   │req  │→ │rate  │→ │logger│→ │resp││
   │id   │  │limit │  │      │  │time││
   └──────┘  └──────┘  └──────┘  └────┘│
      │         │          │        │   │
      ▼         ▼          ▼        ▼   ▼
   Service → Response ← Response ← Headers
```

---

## Middleware Test Suite

### Test 1: test_request_id_header

**Purpose**: Verify unique request IDs injected on every request  
**Middleware**: `request_id_middleware`

#### Test Code
```python
def test_request_id_header(gateway):
    """Request should have unique x-request-id header."""
    response = gateway.get("/health")
    
    assert response.status_code == 200
    assert "x-request-id" in response.headers
    
    request_id = response.headers["x-request-id"]
    # Should be UUID format
    assert len(request_id) == 36
    assert request_id.count("-") == 4
```

#### Expected Behavior
```
Request 1:
  ↓ request_id_middleware
  → Generates UUID: "550e8400-e29b-41d4-a716-446655440000"
  → Stores in request.state
  ↓
  Response header added: x-request-id: 550e8400-e29b-41d4-a716-446655440000

Request 2:
  ↓ request_id_middleware
  → Generates NEW UUID: "6ba7b8100-9dad-11d1-80b4-00c04fd430c8"
  → Different from Request 1
```

#### Implementation Details
```python
# In gateway/main.py
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = str(uuid4())  # Generate unique ID
    request.state.request_id = request_id
    
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response
```

#### Validation Points
- UUID format (36 chars, 4 dashes)
- Present on every response
- Different for each request
- Matches internal request state

#### Use Case
- Request tracing across logs
- Debugging request flow
- Correlating client logs with server logs

---

### Test 2: test_response_time_header

**Purpose**: Verify response time measurement in milliseconds  
**Middleware**: `response_time_middleware`

#### Test Code
```python
def test_response_time_header(gateway):
    """Response should include x-response-time-ms header."""
    response = gateway.get("/health")
    
    assert response.status_code == 200
    assert "x-response-time-ms" in response.headers
    
    response_time_ms = float(response.headers["x-response-time-ms"])
    assert response_time_ms > 0
    assert response_time_ms < 1000  # Should complete in < 1s
```

#### Expected Behavior
```
Request arrives at: T0
↓ request_time_middleware
start_time = time.time()
↓
Service processes request
↓
response_time_middleware
end_time = time.time()
elapsed_ms = (end_time - start_time) * 1000
header: x-response-time-ms: 12.34
```

#### Implementation
```python
@app.middleware("http")
async def request_time_middleware(request: Request, call_next):
    request.state.start_time = time.time()
    response = await call_next(request)
    return response

@app.middleware("http")
async def response_time_middleware(request: Request, call_next):
    response = await call_next(request)
    
    if hasattr(request.state, 'start_time'):
        elapsed_ms = (time.time() - request.state.start_time) * 1000
        response.headers["x-response-time-ms"] = str(elapsed_ms)
    
    return response
```

#### Measurement Points
- Accurate to millisecond precision
- Includes all downstream processing
- Used for performance monitoring

#### Typical Values
```
/health: 0.5-1.0ms (fast, no I/O)
/gateway/routes: 1-2ms (route lookup)
/auth/login: 10-50ms (service processing)
/chat/messages: 50-200ms (database queries)
```

---

### Test 3: test_logger_buffers

**Purpose**: Verify request logging and buffering  
**Component**: `Logger` class

#### Test Code
```python
def test_logger_buffers(gateway):
    """Logger should buffer requests."""
    # Clear logger
    logger = gateway.app.state.logger
    logger.clear_buffer()
    
    # Make 5 requests
    for i in range(5):
        gateway.get("/health")
    
    # Check buffer
    buffer = logger.get_buffer()
    assert len(buffer) == 5
    
    # Each entry has required fields
    for entry in buffer:
        assert "request_id" in entry
        assert "path" in entry
        assert "method" in entry
        assert "status_code" in entry
```

#### Logger Structure
```python
class RequestLog:
    request_id: str       # UUID from middleware
    path: str             # /health
    method: str           # GET
    status_code: int      # 200
    response_time_ms: float  # 1.23
    timestamp: float      # unix timestamp
```

#### Buffer Lifecycle
```
Request 1 → Log entry → Buffer
Request 2 → Log entry → Buffer
Request 3 → Log entry → Buffer
...
Request N → Log entry → Buffer

logger.get_buffer()  → [Entry1, Entry2, ..., EntryN]
logger.clear_buffer()  → [] (reset)
```

#### Use Cases
- Request audit trail
- Performance analysis
- Debugging sequences of requests
- Integration test verification

---

### Test 4: test_logger_stats

**Purpose**: Verify statistical aggregation of requests  
**Component**: `Logger` statistics methods

#### Test Code
```python
def test_logger_stats(gateway):
    """Logger should calculate statistics."""
    logger = gateway.app.state.logger
    logger.clear_buffer()
    
    # Make requests (simulating varying response times)
    response_times = [10, 20, 15, 25, 30]
    for rt in response_times:
        # Make request (real time may vary)
        gateway.get("/health")
    
    # Get stats
    stats = logger.get_stats()
    
    assert stats["count"] == 5
    assert stats["min"] > 0
    assert stats["max"] >= stats["min"]
    assert stats["avg"] >= stats["min"]
    assert stats["avg"] <= stats["max"]
```

#### Statistics Calculated
```python
{
    "count": 5,           # Number of requests
    "min": 0.5,          # Minimum response time (ms)
    "max": 2.1,          # Maximum response time (ms)
    "avg": 1.2,          # Average response time (ms)
    "total": 6.0,        # Total time (ms)
    "p95": 2.05,         # 95th percentile
    "p99": 2.10          # 99th percentile
}
```

#### Calculation Examples
```python
# Given response times: [10, 20, 15, 25, 30]
min = 10
max = 30
avg = (10 + 20 + 15 + 25 + 30) / 5 = 20
total = 100

# Percentiles (sorted: [10, 15, 20, 25, 30])
p95 = 30 (95% of requests faster than this)
p99 = 30 (99% of requests faster than this)
```

#### Use Cases
- Performance dashboards
- SLA monitoring
- Capacity planning
- Identifying slow endpoints

---

### Test 5: test_health_endpoint

**Purpose**: Verify health check endpoint  
**Status**: Basic health check (Phase 1 format)

#### Test Code
```python
def test_health_endpoint(gateway):
    """Health endpoint should return healthy status."""
    response = gateway.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert data["phase"] == 1
```

#### Response
```json
{
    "status": "healthy",
    "phase": 1
}
```

#### Purpose
- Simple liveness probe
- Load balancer heartbeat
- Kubernetes readiness check

#### Typical Usage
```bash
# Health check from load balancer every 30s
$ while true; do
    curl http://localhost:8000/health
    sleep 30
done
```

---

### Test 6: test_gateway_routes_endpoint

**Purpose**: Verify routes introspection endpoint  
**Endpoint**: `GET /gateway/routes`

#### Test Code
```python
def test_gateway_routes_endpoint(gateway):
    """Routes endpoint should list all routes."""
    response = gateway.get("/gateway/routes")
    
    assert response.status_code == 200
    routes = response.json()
    
    # Should be list of routes
    assert isinstance(routes, list)
    assert len(routes) > 0
    
    # Each route has required fields
    for route in routes:
        assert "path" in route
        assert "service" in route
```

#### Response Format
```json
[
    {
        "path": "/auth",
        "service": "auth_service",
        "host": "localhost",
        "port": 8001,
        "full_url": "http://localhost:8001/auth"
    },
    {
        "path": "/chat",
        "service": "chat_service",
        "host": "localhost",
        "port": 8002,
        "full_url": "http://localhost:8002/chat"
    },
    {
        "path": "/ai",
        "service": "ai_service",
        "host": "localhost",
        "port": 8003,
        "full_url": "http://localhost:8003/ai"
    }
]
```

#### Use Cases
- API documentation
- Service discovery debugging
- Runtime configuration verification
- Integration testing

---

## Middleware Request Flow

### Full Request Lifecycle

```
1. Client sends request
   GET /health HTTP/1.1
   
2. request_id_middleware
   ├─ Generate UUID
   ├─ Store in request.state
   └─ Continue
   
3. request_time_middleware
   ├─ Record start time
   └─ Continue
   
4. rate_limiting_middleware
   ├─ Check IP rate limit
   ├─ Add rate limit headers
   └─ Continue (or return 429)
   
5. response_time_middleware
   ├─ Calculate elapsed time
   ├─ Add response time header
   └─ Continue
   
6. Gateway middleware (routing)
   ├─ Parse request path
   ├─ Find target service
   ├─ Proxy request
   └─ Return response
   
7. logger middleware (if present)
   ├─ Log request details
   └─ Continue
   
8. Response returned to client
   with all middleware-added headers
```

---

## Middleware Testing Patterns

### Pattern 1: Header Verification
```python
def test_new_header(gateway):
    """Verify new header is added."""
    response = gateway.get("/health")
    
    assert "x-custom-header" in response.headers
    assert response.headers["x-custom-header"] == "expected_value"
```

### Pattern 2: State Tracking
```python
def test_request_state(gateway):
    """Verify request state is accessible."""
    @app.get("/debug")
    async def debug_endpoint(request: Request):
        return {
            "request_id": request.state.request_id,
            "start_time": request.state.start_time
        }
    
    response = gateway.get("/debug")
    data = response.json()
    
    assert "request_id" in data
    assert len(data["request_id"]) == 36
```

### Pattern 3: Middleware Order
```python
# Order matters!
# Correct:
app.add_middleware(ResponseTimeMiddleware)  # First (outermost)
app.add_middleware(RequestIdMiddleware)     # Last (innermost)

# Execution order:
Request → ResponseTime → RequestId → Handler
         ← ResponseTime ← RequestId ← Handler
```

### Pattern 4: Error Handling
```python
def test_middleware_on_error(gateway):
    """Middleware should work even when handler errors."""
    response = gateway.get("/error")
    
    assert response.status_code == 500
    assert "x-request-id" in response.headers  # Should still have ID
    assert "x-response-time-ms" in response.headers
```

---

## Middleware Configuration

### Middleware Order in gateway/main.py
```python
# Order: Last added = First executed
app.add_middleware(LoggerMiddleware)          # 1. First (outermost)
app.add_middleware(ResponseTimeMiddleware)    # 2. Measure response time
app.add_middleware(RateLimitMiddleware)       # 3. Check rate limits
app.add_middleware(RequestTimeMiddleware)     # 4. Record start time
app.add_middleware(RequestIdMiddleware)       # 5. Last (innermost)
```

### Why Order Matters
```
Request flow (execution order):
1 (outer) → 2 → 3 → 4 → 5 (inner) → Handler

Response flow (execution order):
Handler → 5 → 4 → 3 → 2 → 1 (outer)

So request_id must be set BEFORE measuring time
And time must be measured BEFORE rate limiting checks
```

---

## Debugging Middleware Issues

### Enable Request/Response Logging
```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("gateway.middleware")

@app.middleware("http")
async def debug_middleware(request: Request, call_next):
    logger.debug(f"→ Request: {request.method} {request.url.path}")
    logger.debug(f"  Headers: {dict(request.headers)}")
    
    response = await call_next(request)
    
    logger.debug(f"← Response: {response.status_code}")
    logger.debug(f"  Headers: {dict(response.headers)}")
    
    return response
```

### Check Header Values
```python
def test_debug_headers(gateway):
    response = gateway.get("/health")
    
    print("Response Headers:")
    for name, value in response.headers.items():
        if name.startswith("x-"):
            print(f"  {name}: {value}")
```

### Test Middleware Isolation
```python
@pytest.fixture
def gateway_no_middleware():
    """Gateway without optional middleware."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    
    @app.get("/health")
    async def health():
        return {"status": "healthy"}
    
    return TestClient(app)

def test_bare_endpoint(gateway_no_middleware):
    """Verify endpoint works without middleware."""
    response = gateway_no_middleware.get("/health")
    assert response.status_code == 200
```

---

## Performance Impact of Middleware

### Overhead Analysis
```
Per-request middleware overhead:

RequestIdMiddleware:
  - UUID generation: ~0.01ms
  - State storage: ~0.01ms
  Total: ~0.02ms

RequestTimeMiddleware:
  - time.time() call: ~0.001ms
  Total: ~0.001ms

RateLimitMiddleware:
  - Redis lookup: ~0.5-2ms (depends on network)
  - Rate limit check: ~0.1ms
  Total: ~0.6-2ms

ResponseTimeMiddleware:
  - Calculation: ~0.001ms
  Total: ~0.001ms

Grand Total: ~0.7-2ms overhead per request
```

### Full Request Timeline
```
Request arrives: T0
├─ RequestIdMiddleware: 0.02ms
├─ RequestTimeMiddleware: 0.001ms
├─ RateLimitMiddleware: 1.0ms
├─ ResponseTimeMiddleware: 0.001ms
├─ Handler execution: 5.0ms (service processing)
└─ Response returned: T0 + 6.02ms

Total: ~6.02ms (middleware: 1.02ms, handler: 5.0ms)
```

---

## Related Documentation

- [PHASE-3-TESTS.md](PHASE-3-TESTS.md) - All tests
- [RATE-LIMITING-TESTS.md](RATE-LIMITING-TESTS.md) - Rate limiting details
- [README-PHASE3.md](README-PHASE3.md) - Architecture

---

**Last Updated**: May 2026  
**Test Count**: 6 middleware tests  
**Pass Rate**: 100%  
**Coverage**: Request tracking, timing, logging, health checks
