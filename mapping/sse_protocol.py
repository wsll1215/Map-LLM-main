"""Transport-neutral helpers for the map-building SSE stream."""

from __future__ import annotations

import asyncio
import inspect
import json
import queue
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, AsyncIterator, DefaultDict, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs


# ``request_*`` events describe the terminal state for compatibility. ``done``
# is the sole transport terminator so the state event and final envelope are
# both delivered before a multiplexed stream closes.
TERMINAL_EVENTS = {"done"}
_CURSOR_PATTERN = re.compile(r"^\d+(?:-\d+)?$")


class StreamRequestError(ValueError):
    def __init__(
        self, error_code: str, message: str, *, details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}

    def as_payload(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error_code": self.error_code,
            "message": str(self),
            "retryable": False,
            "next_action": "fix_stream_request",
            "details": self.details,
        }


def parse_stream_request(
    raw_query: Union[bytes, str], *, max_requests: int = 20
) -> Tuple[List[str], Dict[str, str]]:
    """Parse a multiplex request and validate that every cursor belongs to it."""
    if isinstance(raw_query, bytes):
        raw_query = raw_query.decode("ascii", errors="ignore")
    query = parse_qs(raw_query, keep_blank_values=True)
    raw_ids = query.get("request_ids", [""])[0]
    request_ids = [item.strip() for item in raw_ids.split(",") if item.strip()]
    if (
        not request_ids
        or len(request_ids) > max_requests
        or any(not item.isdigit() for item in request_ids)
    ):
        raise StreamRequestError(
            "invalid_stream_request", "request_ids 必须包含一个或多个数字 ID"
        )
    request_ids = list(dict.fromkeys(request_ids))
    cursor_param = "cursors" if query.get("cursors") is not None else "after"
    raw_cursors = (query.get(cursor_param) or ["{}"])[0]
    try:
        cursors = json.loads(raw_cursors or "{}")
    except json.JSONDecodeError as exc:
        if cursor_param == "after" and len(request_ids) == 1 and raw_cursors:
            cursors = raw_cursors
        else:
            raise StreamRequestError(
                "invalid_stream_cursor", "cursors 不是有效 JSON"
            ) from exc
    if not isinstance(cursors, dict):
        if len(request_ids) != 1:
            raise StreamRequestError(
                "invalid_stream_cursor", "多任务订阅必须使用游标对象"
            )
        cursors = {request_ids[0]: raw_cursors}
    if any(str(key) not in request_ids for key in cursors):
        raise StreamRequestError(
            "invalid_stream_cursor",
            "游标只能对应 request_ids 中的任务",
        )
    normalized: Dict[str, str] = {}
    for key, value in cursors.items():
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise StreamRequestError("invalid_stream_cursor", "游标必须是字符串或整数")
        normalized[str(key)] = validate_stream_cursor(value)
    return request_ids, normalized


def validate_stream_cursor(value: Any) -> str:
    """Validate a Redis Stream or in-memory numeric cursor."""
    if value is None or value == "":
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise StreamRequestError("invalid_stream_cursor", "游标必须是字符串或整数")
    cursor = str(value)
    if not _CURSOR_PATTERN.fullmatch(cursor):
        raise StreamRequestError("invalid_stream_cursor", "游标格式必须为 N 或 N-M")
    return cursor


def format_sse_event(*, event_id: str, event_name: str, payload: Dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    event_name: str
    payload: Dict[str, Any]


class InMemoryEventBroker:
    """Bounded local broker with request-scoped cursors and live fan-out."""

    def __init__(
        self, *, max_events: int = 1000, coalesce_window_ms: int = 200
    ) -> None:
        self.max_events = max_events
        self.coalesce_window_ms = coalesce_window_ms
        self._events: DefaultDict[str, List[EventRecord]] = defaultdict(list)
        self._subscribers: DefaultDict[str, List[queue.Queue[EventRecord]]] = (
            defaultdict(list)
        )
        self._next_ids: DefaultDict[str, int] = defaultdict(int)
        self._coalesced: Dict[Tuple[str, str], Tuple[float, str]] = {}
        self._lock = threading.RLock()

    async def publish(
        self, request_key: str, event_name: str, payload: Dict[str, Any]
    ) -> str:
        return self.publish_sync(request_key, event_name, payload)

    def publish_sync(
        self, request_key: str, event_name: str, payload: Dict[str, Any]
    ) -> str:
        now = time.monotonic()
        coalesce_key = None
        if isinstance(payload, dict):
            coalesce_key = payload.get("_coalesce_key") or payload.get("coalesce_key")
        with self._lock:
            if coalesce_key:
                previous = self._coalesced.get((request_key, str(coalesce_key)))
                if previous and (now - previous[0]) * 1000 <= self.coalesce_window_ms:
                    return previous[1]
            self._next_ids[request_key] += 1
            event_id = str(self._next_ids[request_key])
            event_payload = dict(payload)
            event_payload.pop("_coalesce_key", None)
            event_payload.setdefault("event_seq", self._next_ids[request_key])
            event = EventRecord(event_id, event_name, event_payload)
            events = self._events[request_key]
            events.append(event)
            del events[: -self.max_events]
            if coalesce_key:
                self._coalesced[(request_key, str(coalesce_key))] = (now, event_id)
            subscribers = tuple(self._subscribers[request_key])
        for subscriber in subscribers:
            subscriber.put_nowait(event)
        return event_id

    def retained_events(self, request_key: str) -> List[EventRecord]:
        with self._lock:
            return list(self._events[request_key])

    def latest_event_ids(self, request_keys: List[str]) -> Dict[str, str]:
        """Return a snapshot cursor for local fallback streams.

        Redis is the durable history. The in-process broker is only a live
        degradation channel, so a healthy Redis subscriber must start the
        local side at its current tail instead of replaying old fallback
        events and duplicating the Redis backlog.
        """
        with self._lock:
            return {
                str(key): (self._events[str(key)][-1].event_id if self._events[str(key)] else "0")
                for key in request_keys
            }

    @staticmethod
    def _cursor_value(value: Optional[str]) -> int:
        try:
            return int(str(value or "0").split("-", 1)[0])
        except (TypeError, ValueError):
            return 0

    async def subscribe(
        self, request_key: str, after_id: Optional[str] = None
    ) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        cursor = self._cursor_value(after_id)
        subscriber_queue: queue.Queue[EventRecord] = queue.Queue()
        with self._lock:
            self._subscribers[request_key].append(subscriber_queue)
            # Register before taking the snapshot so a publish cannot land in
            # the gap between snapshot and subscription. Duplicate delivery
            # is filtered by the cursor below.
            retained = list(self._events[request_key])
        try:
            for event in retained:
                if int(event.event_id) <= cursor:
                    continue
                cursor = int(event.event_id)
                yield event.event_id, event.event_name, event.payload
                if event.event_name in TERMINAL_EVENTS:
                    return

            while True:
                try:
                    event = subscriber_queue.get_nowait()
                except queue.Empty:
                    # Polling keeps cancellation deterministic. A blocking
                    # ``to_thread(queue.get)`` can survive an SSE disconnect
                    # and retain a worker thread indefinitely.
                    await asyncio.sleep(0.05)
                    continue
                if int(event.event_id) <= cursor:
                    continue
                cursor = int(event.event_id)
                yield event.event_id, event.event_name, event.payload
                if event.event_name in TERMINAL_EVENTS:
                    return
        finally:
            with self._lock:
                subscribers = self._subscribers[request_key]
                if subscriber_queue in subscribers:
                    subscribers.remove(subscriber_queue)

    async def subscribe_many(
        self, request_keys: List[str], cursors: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Tuple[str, str, str, Dict[str, Any]]]:
        """Multiplex request streams while preserving each request's cursor."""
        cursors = cursors or {}
        pending: Dict[str, AsyncIterator[Tuple[str, str, Dict[str, Any]]]] = {
            key: self.subscribe(key, after_id=cursors.get(key)).__aiter__()
            for key in request_keys
        }
        tasks = {
            key: asyncio.create_task(iterator.__anext__())
            for key, iterator in pending.items()
        }
        try:
            while tasks:
                done, _ = await asyncio.wait(
                    tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    key = next(item for item, value in tasks.items() if value is task)
                    del tasks[key]
                    try:
                        event_id, event_name, payload = task.result()
                    except StopAsyncIteration:
                        continue
                    yield key, event_id, event_name, payload
                    tasks[key] = asyncio.create_task(pending[key].__anext__())
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)


class RedisStreamBroker:
    """Redis Streams broker with shared sync/async clients and bounded history."""

    def __init__(
        self,
        redis_url: str,
        *,
        maxlen: int = 1000,
        ttl_seconds: int = 86400,
        max_connections: int = 50,
        coalesce_window_ms: int = 200,
        sync_client_factory: Any = None,
        async_client_factory: Any = None,
    ) -> None:
        self.redis_url = redis_url
        self.maxlen = maxlen
        self.ttl_seconds = ttl_seconds
        self.max_connections = max_connections
        self.coalesce_window_ms = coalesce_window_ms
        self._sync_client_factory = sync_client_factory
        self._async_client_factory = async_client_factory
        self._sync_client = None
        self._async_client = None
        self._client_lock = threading.Lock()
        self._coalesced: Dict[Tuple[str, str], Tuple[float, str]] = {}

    @staticmethod
    def _stream_key(request_key: str) -> str:
        return f"mapping:events:{request_key}"

    def _get_sync_client(self) -> Any:
        if self._sync_client is None:
            with self._client_lock:
                if self._sync_client is None:
                    if self._sync_client_factory:
                        self._sync_client = self._sync_client_factory()
                    else:
                        import redis

                        self._sync_client = redis.Redis.from_url(
                            self.redis_url,
                            decode_responses=True,
                            max_connections=self.max_connections,
                        )
        return self._sync_client

    def _get_async_client(self) -> Any:
        if self._async_client is None:
            with self._client_lock:
                if self._async_client is None:
                    if self._async_client_factory:
                        self._async_client = self._async_client_factory()
                    else:
                        import redis.asyncio as redis_async

                        self._async_client = redis_async.from_url(
                            self.redis_url,
                            decode_responses=True,
                            max_connections=self.max_connections,
                        )
        return self._async_client

    @staticmethod
    def _stream_id_parts(value: Any) -> Tuple[int, int]:
        raw = str(value or "0-0")
        major, _, minor = raw.partition("-")
        try:
            return int(major), int(minor or 0)
        except ValueError:
            return 0, 0

    async def _cursor_gap(
        self, client: Any, request_key: str, cursor: str
    ) -> Optional[str]:
        """Return the first retained ID when a cursor fell out of the stream."""
        if not cursor or cursor in {"0", "0-0"}:
            return None
        xinfo_stream = getattr(client, "xinfo_stream", None)
        if xinfo_stream is None:
            return None
        try:
            info = xinfo_stream(self._stream_key(request_key))
            if inspect.isawaitable(info):
                info = await info
            first_entry = info.get("first-entry") or info.get(b"first-entry")
            first_id = first_entry[0] if first_entry else None
        except Exception:
            return None
        if first_id is None:
            return None
        if self._stream_id_parts(cursor) < self._stream_id_parts(first_id):
            return str(first_id)
        return None

    def publish_sync(
        self, request_key: str, event_name: str, payload: Dict[str, Any]
    ) -> str:
        coalesce_key = payload.get("_coalesce_key") or payload.get("coalesce_key")
        now = time.monotonic()
        if coalesce_key:
            previous = self._coalesced.get((request_key, str(coalesce_key)))
            if previous and (now - previous[0]) * 1000 <= self.coalesce_window_ms:
                return previous[1]
        try:
            client = self._get_sync_client()
            stream_key = self._stream_key(request_key)
            sequence = client.incr(f"{stream_key}:seq")
            client.expire(f"{stream_key}:seq", self.ttl_seconds)
            event_payload = dict(payload)
            event_payload.pop("_coalesce_key", None)
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
            if coalesce_key:
                self._coalesced[(request_key, str(coalesce_key))] = (now, str(event_id))
            return str(event_id)
        except Exception:
            fallback = dict(payload)
            fallback.setdefault("transport_status", "degraded")
            fallback.setdefault(
                "transport_error", "Redis 实时通道不可用，已降级为本地事件队列"
            )
            return get_default_broker().publish_sync(request_key, event_name, fallback)

    async def subscribe(
        self, request_key: str, after_id: Optional[str] = None
    ) -> AsyncIterator[Tuple[str, str, Dict[str, Any]]]:
        async for _key, event_id, event_name, payload in self.subscribe_many(
            [request_key], {request_key: after_id} if after_id else None
        ):
            yield event_id, event_name, payload

    async def subscribe_many(
        self, request_keys: List[str], cursors: Optional[Dict[str, str]] = None
    ) -> AsyncIterator[Tuple[str, str, str, Dict[str, Any]]]:
        """Read Redis and local degradation events through one shared client.

        A publisher can lose Redis between two successful ``XREAD`` calls. The
        local iterator is therefore kept alive beside Redis instead of only
        being used after the Redis reader has already failed.
        """
        active = set(str(key) for key in request_keys)
        if not active:
            return
        cursors = {key: (cursors or {}).get(key) or "0-0" for key in active}
        redis_active = active

        async def redis_events() -> AsyncIterator[Tuple[str, str, str, Dict[str, Any]]]:
            failure_attempt = 0
            failure_reported = False
            while redis_active:
                try:
                    client = self._get_async_client()
                    for key in list(redis_active):
                        first_retained_id = await self._cursor_gap(
                            client, key, cursors[key]
                        )
                        if first_retained_id is None:
                            continue
                        yield key, f"redis-gap-{key}", "stream_error", {
                            "request_id": int(key),
                            "error_code": "stream_cursor_gap",
                            "message": "实时事件已超出保留窗口，正在从可用事件重新同步",
                            "retryable": False,
                            "next_action": "refresh_task_state",
                            "details": {
                                "requested_cursor": cursors[key],
                                "first_retained_id": first_retained_id,
                            },
                        }
                        cursors[key] = "0-0"
                    streams = {
                        self._stream_key(key): cursors[key] for key in redis_active
                    }
                    response = await client.xread(streams, count=100, block=15000)
                    failure_attempt = 0
                    failure_reported = False
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failure_attempt += 1
                    if not failure_reported:
                        failure_reported = True
                        for key in list(redis_active):
                            yield key, f"redis-error-{key}", "stream_error", {
                                "request_id": int(key),
                                "error_code": "redis_unavailable",
                                "message": "Redis 实时通道暂时不可用，正在重试并监听降级通道",
                                "retryable": True,
                                "next_action": "retry_stream",
                                "details": {"exception_type": type(exc).__name__},
                            }
                    await asyncio.sleep(min(0.5 * (2 ** (failure_attempt - 1)), 8.0))
                    continue
                if not response:
                    continue
                for stream_key, entries in response:
                    key = str(stream_key).rsplit(":", 1)[-1]
                    if key not in redis_active:
                        continue
                    for event_id, fields in entries:
                        event_id = str(event_id)
                        cursors[key] = event_id
                        event_name = str(fields.get("event", "message"))
                        try:
                            payload = json.loads(fields.get("payload", "{}"))
                            if not isinstance(payload, dict):
                                raise ValueError("payload must be an object")
                        except (TypeError, ValueError, json.JSONDecodeError):
                            yield key, event_id, "stream_error", {
                                "request_id": int(key),
                                "error_code": "malformed_event",
                                "message": "实时通道收到格式错误的事件，已跳过",
                                "retryable": False,
                                "next_action": "inspect_trace",
                                "source_event_id": event_id,
                            }
                            continue
                        yield key, event_id, event_name, payload
                        if event_name in TERMINAL_EVENTS:
                            redis_active.discard(key)

        redis_iterator = redis_events().__aiter__()
        fallback_broker = get_default_broker()
        local_iterator = fallback_broker.subscribe_many(
            list(active), fallback_broker.latest_event_ids(list(active))
        ).__aiter__()
        tasks = {
            "redis": asyncio.create_task(redis_iterator.__anext__()),
            "local": asyncio.create_task(local_iterator.__anext__()),
        }
        try:
            while active and tasks:
                completed, _ = await asyncio.wait(
                    tasks.values(), return_when=asyncio.FIRST_COMPLETED
                )
                for task in completed:
                    source = next(
                        name for name, candidate in tasks.items() if candidate is task
                    )
                    del tasks[source]
                    try:
                        event = task.result()
                    except StopAsyncIteration:
                        if source == "redis" and redis_active:
                            redis_iterator = redis_events().__aiter__()
                            tasks[source] = asyncio.create_task(
                                redis_iterator.__anext__()
                            )
                        continue
                    except Exception:
                        # Keep a failed reader alive so Redis recovery can be
                        # observed without requiring the browser to reconnect.
                        if source == "redis" and redis_active:
                            tasks[source] = asyncio.create_task(
                                redis_iterator.__anext__()
                            )
                        continue
                    key, event_id, event_name, payload = event
                    if key in active:
                        yield key, event_id, event_name, payload
                        if event_name in TERMINAL_EVENTS:
                            active.remove(key)
                    if active:
                        iterator = (
                            redis_iterator if source == "redis" else local_iterator
                        )
                        tasks[source] = asyncio.create_task(iterator.__anext__())
        except asyncio.CancelledError:
            raise
        finally:
            for task in tasks.values():
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks.values(), return_exceptions=True)
            for iterator in (redis_iterator, local_iterator):
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    await close()

    async def aclose(self) -> None:
        client = self._async_client
        self._async_client = None
        if client is not None:
            close = getattr(client, "aclose", None)
            if close:
                await close()

    def close(self) -> None:
        client = self._sync_client
        self._sync_client = None
        if client is not None:
            close = getattr(client, "close", None)
            if close:
                close()

        async_client = self._async_client
        self._async_client = None
        if async_client is None:
            return
        close_async = getattr(async_client, "aclose", None)
        if close_async is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(close_async())
        else:
            loop.create_task(close_async())


_default_broker = InMemoryEventBroker()
_redis_brokers: Dict[str, RedisStreamBroker] = {}
_redis_brokers_lock = threading.Lock()


def get_default_broker() -> InMemoryEventBroker:
    return _default_broker


def reset_event_broker_cache() -> None:
    """Close cached Redis clients; intended for tests and process shutdown."""
    with _redis_brokers_lock:
        brokers = list(_redis_brokers.values())
        _redis_brokers.clear()
    for broker in brokers:
        broker.close()


def get_event_broker() -> Any:
    try:
        from django.conf import settings

        redis_url = getattr(settings, "REDIS_URL", "")
    except Exception:
        redis_url = ""
    if not redis_url:
        return _default_broker
    try:
        from django.conf import settings

        maxlen = int(getattr(settings, "MAP_SSE_REDIS_MAXLEN", 1000))
        ttl_seconds = int(getattr(settings, "MAP_SSE_REDIS_TTL_SECONDS", 86400))
        max_connections = int(getattr(settings, "MAP_SSE_REDIS_MAX_CONNECTIONS", 50))
        coalesce_window_ms = int(getattr(settings, "MAP_SSE_COALESCE_WINDOW_MS", 200))
    except Exception:
        maxlen, ttl_seconds, max_connections, coalesce_window_ms = 1000, 86400, 50, 200
    with _redis_brokers_lock:
        broker = _redis_brokers.get(redis_url)
        if broker is None:
            broker = RedisStreamBroker(
                redis_url,
                maxlen=maxlen,
                ttl_seconds=ttl_seconds,
                max_connections=max_connections,
                coalesce_window_ms=coalesce_window_ms,
            )
            _redis_brokers[redis_url] = broker
        return broker
