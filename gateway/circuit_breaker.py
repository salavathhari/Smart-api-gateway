import asyncio
import time
from enum import Enum
from typing import Dict, Optional, Callable, Any

class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered

class CircuitBreaker:
    """
    Circuit Breaker pattern for handling service failures.
    
    Compatible with local service-map based state and upstream call-based state.
    """
    
    def __init__(
        self,
        service_name: Optional[str] = None,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0
    ):
        """
        Initialize circuit breaker.
        
        If service_name is provided, it acts as a single-service breaker.
        Otherwise, it acts as a multi-service manager (legacy support).
        """
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        
        # Single-service state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        
        # Multi-service state (for local main.py)
        self.states: Dict[str, CircuitState] = {}
        self.failure_counts: Dict[str, int] = {}
        self.last_failure_times: Dict[str, float] = {}

    def get_state(self, service_name: Optional[str] = None) -> str:
        """Get the current state of the circuit (as a string)."""
        name = service_name or self.service_name
        if not name:
            return self.state.value

        state = self.states.get(name, CircuitState.CLOSED)
        
        if state == CircuitState.OPEN:
            last_fail = self.last_failure_times.get(name, 0)
            if time.time() - last_fail > self.recovery_timeout:
                print(f"🔄 {name}: Circuit HALF_OPEN (recovery timeout elapsed)")
                self.states[name] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN.value
        
        return state.value

    def record_success(self, service_name: Optional[str] = None):
        """Reset failures on successful request."""
        name = service_name or self.service_name
        if not name:
            if self.state == CircuitState.HALF_OPEN:
                print(f"🟢 {self.service_name}: Circuit CLOSED (recovered)")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
            return

        state = self.states.get(name, CircuitState.CLOSED)
        if state == CircuitState.HALF_OPEN:
            print(f"✅ Circuit for {name} CLOSED (successfully recovered)")
            self.states[name] = CircuitState.CLOSED
        
        self.failure_counts[name] = 0

    def record_failure(self, service_name: Optional[str] = None):
        """Increment failure count and open circuit if threshold reached."""
        name = service_name or self.service_name
        if not name:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                print(f"🔴 {self.service_name}: Circuit OPEN ({self.failure_count} failures)")
                self.state = CircuitState.OPEN
            return

        count = self.failure_counts.get(name, 0) + 1
        self.failure_counts[name] = count
        self.last_failure_times[name] = time.time()

        if count >= self.failure_threshold:
            if self.states.get(name) != CircuitState.OPEN:
                print(f"🚨 Circuit for {name} OPENED (threshold reached: {count})")
            self.states[name] = CircuitState.OPEN

    def allow_request(self, service_name: Optional[str] = None) -> bool:
        """Check if request is allowed based on circuit state."""
        return self.get_state(service_name) != CircuitState.OPEN.value

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker (Upstream style)."""
        if self.allow_request():
            try:
                result = await func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise
        else:
            raise Exception(f"🔴 {self.service_name}: Circuit OPEN (rejecting)")

# Initialize global circuit breaker for multi-service use
from gateway.config import settings
circuit_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    recovery_timeout=settings.circuit_breaker_recovery_timeout
)
