"""
Metrics Collection and Storage
Tracks service performance: latency, error rate, complexity, load, freshness.
Stores last 20 metrics per service in Redis (no TTL).
"""

import json
import time
from typing import Dict, List, Optional, Any

from gateway.redis_client import redis_client


class MetricsCollector:
    """Collect and store service metrics in Redis."""

    def __init__(self):
        self.metrics_key_prefix = "metrics:service:"
        self.max_history = 20

    async def record_request(
        self,
        service: str,
        task_type: str,
        latency_ms: float,
        status_code: int,
        complexity: str = "low",
        inflight_requests: int = 1,
    ) -> None:
        """
        Record a request metric for a service.

        Args:
            service: Service name (e.g., "chat", "ai", "products")
            task_type: Type of task (e.g., "summarization", "chat", "list")
            latency_ms: Response time in milliseconds
            status_code: HTTP status code
            complexity: Complexity level ("low", "medium", "high")
            inflight_requests: Number of requests currently being processed
        """
        try:
            metric = {
                "timestamp": int(time.time()),
                "service": service,
                "task_type": task_type,
                "latency_ms": latency_ms,
                "status": status_code,
                "success": 200 <= status_code < 300,
                "complexity": complexity,
                "inflight_requests": inflight_requests,
            }

            key = f"{self.metrics_key_prefix}{service}"

            # Get existing metrics
            existing = await redis_client.get(key)
            metrics_list: List[Dict[str, Any]] = []

            if existing:
                try:
                    metrics_list = json.loads(existing)
                except json.JSONDecodeError:
                    metrics_list = []

            # Append new metric
            metrics_list.append(metric)

            # Keep only last N metrics
            if len(metrics_list) > self.max_history:
                metrics_list = metrics_list[-self.max_history :]

            # Store back (no TTL — persistent)
            await redis_client.set(key, json.dumps(metrics_list))

        except Exception as e:
            print(f"⚠️  Error recording metrics for {service}: {e}")

    async def get_metrics(self, service: str) -> Optional[List[Dict[str, Any]]]:
        """Retrieve stored metrics for a service."""
        try:
            key = f"{self.metrics_key_prefix}{service}"
            data = await redis_client.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"⚠️  Error retrieving metrics for {service}: {e}")
            return None

    async def get_service_health(self, service: str) -> Dict[str, Any]:
        """
        Compute health metrics for a service.

        Returns:
            {
                "avg_latency": float,
                "error_rate": float,
                "is_healthy": bool,
                "is_fresh": bool,
                "last_seen": int (unix timestamp),
            }
        """
        metrics_list = await self.get_metrics(service)
        if not metrics_list:
            return {
                "avg_latency": float("inf"),
                "error_rate": 1.0,
                "is_healthy": False,
                "is_fresh": False,
                "last_seen": None,
            }

        # Compute stats
        latencies = [m["latency_ms"] for m in metrics_list]
        successes = sum(1 for m in metrics_list if m["success"])
        total = len(metrics_list)
        error_rate = 1.0 - (successes / total) if total > 0 else 1.0
        last_seen = metrics_list[-1]["timestamp"]
        now = int(time.time())
        age_seconds = now - last_seen

        # Health rules
        is_healthy = error_rate < 0.5  # Less than 50% error rate
        is_fresh = age_seconds < 60  # Metrics younger than 60 seconds

        return {
            "avg_latency": sum(latencies) / len(latencies) if latencies else 0,
            "error_rate": error_rate,
            "is_healthy": is_healthy,
            "is_fresh": is_fresh,
            "last_seen": last_seen,
            "age_seconds": age_seconds,
        }
