"""In-process publish/subscribe for Server-Sent Events, keyed by restaurant.

Single-instance only. To run several API instances, replace publish() with
PostgreSQL NOTIFY and have each instance LISTEN and fan out to its own subscribers.
"""
import asyncio
import json
from collections import defaultdict

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def subscribe(restaurant_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers[restaurant_id].add(q)
    return q


def unsubscribe(restaurant_id: str, q: asyncio.Queue):
    _subscribers[restaurant_id].discard(q)
    if not _subscribers[restaurant_id]:
        _subscribers.pop(restaurant_id, None)


def _deliver(restaurant_id: str, message: str):
    for q in list(_subscribers.get(restaurant_id, ())):
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass  # slow client; it refetches the snapshot on the next event anyway


def publish(restaurant_id: str, event: str, data: dict | None = None):
    """Thread-safe. Call AFTER the database transaction commits."""
    message = f"event: {event}\ndata: {json.dumps(data or {})}\n\n"
    if _loop is None or not _loop.is_running():
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        _deliver(restaurant_id, message)
    else:
        _loop.call_soon_threadsafe(_deliver, restaurant_id, message)
