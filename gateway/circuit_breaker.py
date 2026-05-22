"""
Day 6 — Reliability: Circuit Breaker Implementation.
Prevents cascading failures by stopping requests to failing services.
"""

import time
import asyncio
from typing import Dict, Optional
from enum import Enum

class CircuitState(Enum):
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Failing, no requests allowed
    HALF_OPEN = "HALF_OPEN" # Testing if service recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int, recovery_timeout: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.states: Dict[str, CircuitState] = {}
        self.failure_counts: Dict[str, int] = {}
        self.last_failure_times: Dict[str, float] = {}

    def get_state(self, service_name: str) -> CircuitState:
        """Get the current state of the circuit for a specific service."""
        state = self.states.get(service_name, CircuitState.CLOSED)
        
        if state == CircuitState.OPEN:
            last_fail = self.last_failure_times.get(service_name, 0)
            if time.monotonic() - last_fail > self.recovery_timeout:
                print(f"🔄 Circuit for {service_name} at HALF-OPEN (recovery timeout elapsed)")
                self.states[service_name] = CircuitState.HALF_OPEN
                return CircuitState.HALF_OPEN
        
        return state

    def record_success(self, service_name: str):
        """Reset failures on successful request."""
        state = self.states.get(service_name, CircuitState.CLOSED)
        if state == CircuitState.HALF_OPEN:
            print(f"✅ Circuit for {service_name} CLOSED (successfully recovered)")
            self.states[service_name] = CircuitState.CLOSED
        
        self.failure_counts[service_name] = 0

    def record_failure(self, service_name: str):
        """Increment failure count and open circuit if threshold reached."""
        count = self.failure_counts.get(service_name, 0) + 1
        self.failure_counts[service_name] = count
        self.last_failure_times[service_name] = time.monotonic()

        if count >= self.failure_threshold:
            if self.states.get(service_name) != CircuitState.OPEN:
                print(f"🚨 Circuit for {service_name} OPENED (threshold reached: {count})")
            self.states[service_name] = CircuitState.OPEN

    def allow_request(self, service_name: str) -> bool:
        """Check if request is allowed based on circuit state."""
        state = self.get_state(service_name)
        return state != CircuitState.OPEN

# Initialize global circuit breaker
from gateway.config import settings
circuit_breaker = CircuitBreaker(
    failure_threshold=settings.circuit_breaker_failure_threshold,
    recovery_timeout=settings.circuit_breaker_recovery_timeout
)
