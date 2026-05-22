import asyncio
import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

# Store pool per event loop to handle test isolation
_pools = {}
_clients = {}

def _get_redis_client_for_loop():
    """Get or create Redis client for current event loop."""
    global _pools, _clients
    
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - shouldn't happen in async context
        loop = None
    
    loop_id = id(loop) if loop else None
    
    # Clean up old closed loops
    _pools = {lid: p for lid, p in _pools.items() if lid and p}
    _clients = {lid: c for lid, c in _clients.items() if lid and c}
    
    if loop_id and loop_id not in _clients:
        # Create new pool and client for this loop
        pool = ConnectionPool.from_url(
            "redis://localhost:6379/0",
            decode_responses=True,
            max_connections=10
        )
        client = redis.Redis(connection_pool=pool)
        _pools[loop_id] = pool
        _clients[loop_id] = client
    
    return _clients.get(loop_id)

class RedisClientWrapper:
    """Wrapper that gets the correct client for the current event loop."""
    def __getattr__(self, name):
        client = _get_redis_client_for_loop()
        if client:
            return getattr(client, name)
        raise RuntimeError("No Redis client available - not in async context")

redis_client = RedisClientWrapper()
