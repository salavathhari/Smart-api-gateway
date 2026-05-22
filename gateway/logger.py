
"""
GatewayLogger — structured, async-friendly request logger.

Each log entry is a JSON line so it's easy to ingest into tools like
Loki, Datadog, or just grep.

Phase 1: writes to stdout + in-memory ring buffer (last 500 entries).
Phase 2 will persist to PostgreSQL and stream to Redis pub/sub.
"""

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional


from gateway.database import db_manager

# Configure Python's root logger to output clean lines
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("gateway")


class GatewayLogger:
    MAX_BUFFER = 500  # in-memory ring buffer size

    def __init__(self):
        # Ring buffer of recent log entries for the /gateway/logs endpoint (Phase 2)
        self._buffer: deque[dict] = deque(maxlen=self.MAX_BUFFER)
        self._lock = asyncio.Lock()

    async def log(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        service: str,
        upstream: str,
        status: int,
        latency_ms: float,
        error: Optional[str] = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "method": method,
            "path": path,
            "service": service,
            "upstream": upstream,
            "status": status,
            "latency_ms": round(latency_ms, 2),
        }
        if error:
            entry["error"] = error

        async with self._lock:
            self._buffer.append(entry)

        # 3. MongoDB persistence (Day 7)
        if db_manager.db is not None:
            # Motor methods return awaitables that should be awaited
            await db_manager.db.logs.insert_one(entry.copy())

        # Emoji-prefixed status for human-readable console output
        icon = "✅" if status < 400 else ("⚠️ " if status < 500 else "❌")
        log.info(
            f"{icon} [{request_id}] {method} {path} → {service} "
            f"| {status} | {latency_ms:.1f}ms"
        )

    def recent(self, n: int = 50) -> list[dict]:
        """Return the n most recent log entries (newest last)."""
        entries = list(self._buffer)
        return entries[-n:]

    def stats(self) -> dict:
        """Aggregate stats over the buffered window."""
        entries = list(self._buffer)
        if not entries:
            return {"total": 0}

        total = len(entries)
        errors = sum(1 for e in entries if e["status"] >= 500)
        latencies = [e["latency_ms"] for e in entries]
        avg_latency = sum(latencies) / len(latencies)

        by_service: dict[str, int] = {}
        for e in entries:
            by_service[e["service"]] = by_service.get(e["service"], 0) + 1

        return {
            "total": total,
            "errors": errors,
            "error_rate": round(errors / total * 100, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "by_service": by_service,
        }

    async def get_persisted_logs(self, limit: int = 100) -> list[dict]:
        """Fetch the most recent logs from MongoDB."""
        if db_manager.db is None:
            return self.recent(limit)
        
        cursor = db_manager.db.logs.find({}, {"_id": 0}).sort("ts", -1).limit(limit)
        return await cursor.to_list(length=limit)
