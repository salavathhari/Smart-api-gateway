"""
Load Balancer with Smart Scoring
Implements filter-first, then score approach for service selection.
"""

import time
from typing import Dict, List, Tuple, Optional, Any

from gateway.config import Settings
from gateway.metrics import MetricsCollector


class ServiceScorer:
    """Score services based on multiple criteria."""

    def __init__(self, settings: Settings, metrics: MetricsCollector):
        self.settings = settings
        self.metrics = metrics

    async def get_best_service(
        self,
        task_type: str,
        complexity: str = "low",
    ) -> Optional[str]:
        """
        Filter candidates, then score them, then pick the best.

        ALGORITHM:
        1. Get all services from route table
        2. Filter by:
           - Support the task_type
           - Healthy (error_rate < 50%)
           - Fresh metrics (< 60s old)
        3. Score remaining services
        4. Return the one with the lowest score

        Args:
            task_type: Type of task (e.g., "summarization", "chat")
            complexity: Complexity level ("low", "medium", "high")

        Returns:
            Service name with the best score, or None if no candidates
        """
        route_table = self.settings.route_table

        # 1️⃣ FILTER PHASE
        candidates = []

        for prefix, service_name in route_table.items():
            # Get health metrics
            health = await self.metrics.get_service_health(service_name)

            # Filter criteria
            if not health["is_healthy"]:
                print(f"  ❌ {service_name} - UNHEALTHY (error_rate: {health['error_rate']:.1%})")
                continue

            if not health["is_fresh"]:
                print(f"  ⏱️  {service_name} - STALE (age: {health['age_seconds']}s)")
                continue

            candidates.append(service_name)
            print(f"  ✅ {service_name} - CANDIDATE")

        if not candidates:
            print("⚠️  No healthy candidates available")
            return None

        # 2️⃣ SCORE PHASE
        scores: Dict[str, float] = {}

        for service_name in candidates:
            score = await self._compute_score(service_name, complexity)
            scores[service_name] = score
            print(f"    Score[{service_name}]: {score:.3f}")

        # 3️⃣ SELECT THE BEST
        best_service = min(scores, key=scores.get)
        print(f"🎯 Selected: {best_service} (score: {scores[best_service]:.3f})")

        return best_service

    async def _compute_score(self, service: str, complexity: str) -> float:
        """
        Compute weighted score for a service.

        FORMULA (simplified version):
        score = 0.6 * latency_norm + 0.3 * error_rate_norm + 0.1 * load_norm

        Lower score = better service.
        """
        health = await self.metrics.get_service_health(service)

        # Extract metrics
        avg_latency = health["avg_latency"]
        error_rate = health["error_rate"]

        # For load, we'd need inflight_requests tracking
        # For now, use a placeholder
        load_norm = 0.0

        # Normalize latency (assume max latency is 5000ms)
        max_latency = 5000.0
        latency_norm = min(avg_latency / max_latency, 1.0)

        # Error rate is already normalized (0..1)
        error_rate_norm = error_rate

        # Compute score
        score = 0.6 * latency_norm + 0.3 * error_rate_norm + 0.1 * load_norm

        return score


class LoadBalancer:
    """Main load balancer orchestrator."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.metrics = MetricsCollector()
        self.scorer = ServiceScorer(settings, self.metrics)

    async def get_best_service(self, task_type: str, complexity: str = "low") -> Optional[str]:
        """Get the best service for a task."""
        print(f"\n📊 Load Balancing: task_type={task_type}, complexity={complexity}")
        return await self.scorer.get_best_service(task_type, complexity)

    async def record_request(
        self,
        service: str,
        task_type: str,
        latency_ms: float,
        status_code: int,
        complexity: str = "low",
        inflight_requests: int = 1,
    ) -> None:
        """Record request metrics."""
        await self.metrics.record_request(
            service, task_type, latency_ms, status_code, complexity, inflight_requests
        )
