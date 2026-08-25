"""Transport-neutral helpers for the map-building SSE stream."""

from __future__ import annotations

import asyncio
import json
import queue
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, AsyncIterator, DefaultDict, Dict, List, Optional, Tuple


TERMINAL_EVENTS = {"done", "request_completed", "request_failed", "request_needs_clarification"}


def format_sse_event(*, event_id: str, event_name: str, payload: Dict[str, Any]) -> str:
    """Render one standards-compliant SSE event.

    JSON is kept on one data line so the browser parser can treat each event as
    an atomic payload. The final blank line is required by the SSE protocol.
    """

    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    event_name: str
    payload: Dict[str, Any]


class InMemoryEventBroker:
    """Small async broker used by local development and deterministic tests."""

    def __init__(self) -> None:
        self._events: DefaultDict[str, List[EventRecord]] = defaultdict(list)
        self._subscribers: DefaultDict[str, List[queue.Queue[EventRecord]]] = defaultdict(list)
        self._next_ids: DefaultDict[str, int] = defaultdict(int)

    async def publish(self, request_key: str, event_name: str, payload: Dict[str, Any]) -> str:
        return self.publish_sync(request_key, event_name, payload)

    def publish_sync(self, request_key: str, event_name: str, payload: Dict[str, Any]) -> str:
        self._next_ids[request_key] += 1
        event_id = str(self._next_ids[request_key])
        event_payload = dict(payload)
        event_payload.setdefault("event_seq", self._next_ids[request_key])
        event = EventRecord(event_id, event_name, event_payload)
        self._events[request_key].append(event)
        for subscriber in tuple(self._subscribers[request_key]):
            subscriber.put_nowait(event)
        return event.event_id

    async def subscribe(
        self, request_key: str, after_id: Optional[str] = None
    ) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        """Yield retained events after ``after_id`` and then live events."""

        try:
            cursor = int(after_id or "0")
        except (TypeError, ValueError):
            cursor = 0
        for event in self._events[request_key]:
            if int(event.event_id) <= cursor:
                continue
            cursor = int(event.event_id)
            yield event.event_id, event.event_name, event.payload
            if event.event_name in TERMINAL_EVENTS:
                return

        subscriber_queue: queue.Queue[EventRecord] = queue.Queue()
        self._subscribers[request_key].append(subscriber_queue)
        try:
            while True:
                event = await asyncio.to_thread(subscriber_queue.get)
                if int(event.event_id) <= cursor:
                    continue
                cursor = int(event.event_id)
                yield event.event_id, event.event_name, event.payload
                if event.event_name in TERMINAL_EVENTS:
                    return
        finally:
            subscribers = self._subscribers[request_key]
            if subscriber_queue in subscribers:
                subscribers.remove(subscriber_queue)


class RedisStreamBroker:
    """Redis Streams broker used when the application has a shared Redis URL."""

    def __init__(self, redis_url: str, *, maxlen: int = 1000, ttl_seconds: int = 86400) -> None:
        self.redis_url = redis_url
        self.maxlen = maxlen
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _stream_key(request_key: str) -> str:
        return f"mapping:events:{request_key}"

    def publish_sync(self, request_key: str, event_name: str, payload: Dict[str, Any]) -> str:
        try:
            import redis

            client = redis.Redis.from_url(self.redis_url, decode_responses=True)
            stream_key = self._stream_key(request_key)
            sequence = client.incr(f"{stream_key}:seq")
            client.expire(f"{stream_key}:seq", self.ttl_seconds)
            event_payload = dict(payload)
            event_payload.setdefault("event_seq", sequence)
            event_id = client.xadd(
                stream_key,
                {
                    "event": event_name,
                    "payload": json.dumps(event_payload, ensure_ascii=False),
                },
                maxlen=self.maxlen,
                approximate=True,
            )
            client.expire(stream_key, self.ttl_seconds)
            return str(event_id)
        except Exception:
            # Publishing is best-effort and must never break map generation.
            return ""

    async def subscribe(
        self, request_key: str, after_id: Optional[str] = None
    ) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        try:
            import redis.asyncio as redis_async

            client = redis_async.from_url(self.redis_url, decode_responses=True)
            stream_key = self._stream_key(request_key)
            cursor = after_id or "0-0"
            try:
                while True:
                    response = await client.xread(
                        {stream_key: cursor}, count=100, block=15000
                    )
                    if not response:
                        continue
                    for _key, entries in response:
                        for event_id, fields in entries:
                            cursor = str(event_id)
                            payload = json.loads(fields.get("payload", "{}"))
                            event_name = fields.get("event", "message")
                            yield cursor, event_name, payload
                            if event_name in TERMINAL_EVENTS:
                                return
            finally:
                await client.aclose()
        except Exception:
            return


_default_broker = InMemoryEventBroker()


def get_default_broker() -> InMemoryEventBroker:
    return _default_broker


def get_event_broker() -> Any:
    """Select Redis in deployed environments and memory for local/test runs."""

    try:
        from django.conf import settings

        redis_url = getattr(settings, "REDIS_URL", "")
    except Exception:
        redis_url = ""
    return RedisStreamBroker(redis_url) if redis_url else _default_broker
