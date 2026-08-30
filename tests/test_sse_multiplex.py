import asyncio
import inspect
import json
import sys
import threading
from types import SimpleNamespace

import pytest

from mapping import sse_protocol


def test_parse_stream_request_requires_ids_and_keeps_a_cursor_per_request():
    parser = getattr(sse_protocol, "parse_stream_request", None)
    assert callable(parser), "parse_stream_request is not implemented"
    request_ids, cursors = parser(
        b'request_ids=11,12&cursors=%7B%2211%22%3A%223-0%22%2C%2212%22%3A%227-0%22%7D',
        max_requests=20,
    )

    assert request_ids == ["11", "12"]
    assert cursors == {"11": "3-0", "12": "7-0"}


def test_parse_stream_request_rejects_empty_or_unknown_cursor_ids():
    parser = getattr(sse_protocol, "parse_stream_request", None)
    assert callable(parser), "parse_stream_request is not implemented"
    with pytest.raises(sse_protocol.StreamRequestError) as empty:
        parser(b"request_ids=&cursors=%7B%7D", max_requests=20)
    assert empty.value.error_code == "invalid_stream_request"

    with pytest.raises(sse_protocol.StreamRequestError) as unknown:
        parser(
            b'request_ids=11&cursors=%7B%2212%22%3A%221-0%22%7D',
            max_requests=20,
        )
    assert unknown.value.error_code == "invalid_stream_cursor"


def test_parse_stream_request_accepts_scalar_cursor_for_one_request():
    request_ids, cursors = sse_protocol.parse_stream_request(
        b"request_ids=11&after=3-0", max_requests=20
    )

    assert request_ids == ["11"]
    assert cursors == {"11": "3-0"}


def test_single_stream_cursor_validation_uses_the_same_contract():
    with pytest.raises(sse_protocol.StreamRequestError) as invalid:
        sse_protocol.validate_stream_cursor("not-a-cursor")

    assert invalid.value.error_code == "invalid_stream_cursor"
    assert sse_protocol.validate_stream_cursor("3-0") == "3-0"


def test_parse_stream_request_rejects_non_string_cursor_values():
    with pytest.raises(sse_protocol.StreamRequestError) as invalid:
        sse_protocol.parse_stream_request(
            b'request_ids=11&cursors=%7B%2211%22%3Anull%7D', max_requests=20
        )

    assert invalid.value.error_code == "invalid_stream_cursor"


def test_in_memory_broker_multiplexes_requests_without_crossing_cursors():
    broker_type = getattr(sse_protocol, "InMemoryEventBroker", None)
    assert broker_type is not None, "InMemoryEventBroker is not implemented"
    assert callable(getattr(broker_type, "subscribe_many", None)), (
        "subscribe_many is not implemented"
    )

    async def scenario():
        broker = broker_type()
        await broker.publish("11", "process_log", {"request_id": 11, "step": "a"})
        await broker.publish("12", "process_log", {"request_id": 12, "step": "b"})
        await broker.publish("11", "done", {"request_id": 11})
        await broker.publish("12", "done", {"request_id": 12})

        return [
            event
            async for event in broker.subscribe_many(
                ["11", "12"], {"11": "1", "12": "0"}
            )
        ]

    events = asyncio.run(scenario())

    by_key = {
        key: [name for _key, _id, name, _payload in events if _key == key]
        for key in {event[0] for event in events}
    }
    assert by_key == {"11": ["done"], "12": ["process_log", "done"]}


def test_duplicate_coalescible_events_are_published_once_within_window():
    broker_type = getattr(sse_protocol, "InMemoryEventBroker", None)
    assert broker_type is not None, "InMemoryEventBroker is not implemented"
    assert "coalesce_window_ms" in inspect.signature(broker_type).parameters, (
        "coalesce_window_ms is not implemented"
    )
    broker = broker_type(coalesce_window_ms=200)

    first_id = broker.publish_sync(
        "11", "process_log", {"request_id": 11, "step": "fetch", "coalesce_key": "fetch"}
    )
    second_id = broker.publish_sync(
        "11", "process_log", {"request_id": 11, "step": "fetch", "coalesce_key": "fetch"}
    )

    assert second_id == first_id
    assert len(broker.retained_events("11")) == 1


def test_connection_budget_returns_structured_limit_and_releases_leases():
    from mapping import sse

    budget_type = getattr(sse, "SSEConnectionBudget", None)
    assert budget_type is not None, "SSEConnectionBudget is not implemented"
    budget = budget_type(max_total=1, max_per_user=1, max_per_session=1)
    first = budget.acquire(user_id=7, session_id="browser-a")
    second = budget.acquire(user_id=7, session_id="browser-a")

    assert first.acquired is True
    assert second.acquired is False
    assert second.error_code == "sse_connection_limit"
    assert second.retryable is True
    assert second.next_action == "poll_task_status"

    first.release()
    assert budget.acquire(user_id=7, session_id="browser-a").acquired is True


def test_connection_budget_release_decrements_user_count_once():
    from mapping import sse

    budget = sse.SSEConnectionBudget(max_total=10, max_per_user=2, max_per_session=10)
    first = budget.acquire(user_id=7, session_id="browser-a")
    second = budget.acquire(user_id=7, session_id="browser-b")
    first.release()

    replacement = budget.acquire(user_id=7, session_id="browser-c")

    assert second.acquired is True
    assert replacement.acquired is True
    assert budget.acquire(user_id=7, session_id="browser-d").error_code == "sse_connection_limit"


def test_connection_budget_can_use_a_shared_redis_lease():
    from mapping import sse

    assert "redis_client" in inspect.signature(sse.SSEConnectionBudget).parameters

    class RedisClient:
        def __init__(self):
            self.eval_calls = 0
            self.release_calls = 0

        def eval(self, *_args):
            self.eval_calls += 1
            return 1 if self.eval_calls == 1 else 0

        def zrem(self, *_args):
            self.release_calls += 1

    client = RedisClient()
    budget = sse.SSEConnectionBudget(
        max_total=1,
        max_per_user=1,
        max_per_session=1,
        redis_client=client,
    )

    first = budget.acquire(user_id=7, session_id="browser-a")
    second = budget.acquire(user_id=8, session_id="browser-b")

    assert first.acquired is True
    assert second.error_code == "sse_connection_limit"
    first.release()
    assert client.release_calls == 3


def test_connection_budget_fails_closed_when_redis_is_unavailable():
    from mapping import sse

    class BrokenRedis:
        def eval(self, *_args):
            raise ConnectionError("redis down")

    budget = sse.SSEConnectionBudget(
        max_total=10,
        max_per_user=4,
        max_per_session=1,
        redis_client=BrokenRedis(),
    )

    lease = budget.acquire(user_id=7, session_id="browser-a")

    assert lease.acquired is False
    assert lease.error_code == "sse_budget_unavailable"
    assert lease.retryable is True
    assert lease.next_action == "poll_task_status"


def test_multiplex_sse_returns_429_before_opening_response(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "mapping.models",
        SimpleNamespace(MapRequest=SimpleNamespace()),
    )
    from mapping import sse

    app = sse.MapBuildSSEApplication()
    app._can_access_requests = lambda *_args: _completed(True)
    app.connection_budget = sse.SSEConnectionBudget(
        max_total=0, max_per_user=1, max_per_session=1
    )
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    asyncio.run(
        app(
            {
                "path": "/mapping/api/stream/",
                "method": "GET",
                "query_string": b"request_ids=11,12",
                "user": SimpleNamespace(is_authenticated=True, id=7),
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert messages[0]["status"] == 429
    payload = json.loads(messages[1]["body"])
    assert payload["error_code"] == "sse_connection_limit"
    assert payload["retryable"] is True
    assert payload["next_action"] == "poll_task_status"


def test_multiplex_sse_emits_request_scoped_event_ids_and_keeps_stream_open():
    monkeypatch = pytest.MonkeyPatch()
    try:
        from mapping import sse

        broker = sse_protocol.InMemoryEventBroker()
        broker.publish_sync("11", "process_log", {"request_id": 11, "step": "a"})
        broker.publish_sync("11", "done", {"request_id": 11, "status": "completed"})
        broker.publish_sync("12", "process_log", {"request_id": 12, "step": "b"})
        broker.publish_sync("12", "done", {"request_id": 12, "status": "completed"})

        app = sse.MapBuildSSEApplication()
        app.connection_budget = sse.SSEConnectionBudget(
            max_total=1, max_per_user=1, max_per_session=1
        )
        app._can_access_requests = lambda *_args: _completed(True)
        monkeypatch.setattr(sse, "get_event_broker", lambda: broker)
        messages = []

        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            messages.append(message)

        asyncio.run(
            app(
                {
                    "path": "/mapping/api/stream/",
                    "method": "GET",
                    "query_string": b"request_ids=11,12",
                    "user": SimpleNamespace(is_authenticated=True, id=7),
                    "headers": [],
                },
                receive,
                send,
            )
        )

        bodies = [
            message["body"].decode("utf-8")
            for message in messages
            if message["type"] == "http.response.body"
        ]
        event_bodies = [body for body in bodies if body.startswith("id:")]
        assert len(event_bodies) == 4
        assert {body.splitlines()[0] for body in event_bodies} == {
            "id: 11:1",
            "id: 11:2",
            "id: 12:1",
            "id: 12:2",
        }
        assert all("stream_cursor" in body for body in event_bodies)
    finally:
        monkeypatch.undo()


def test_redis_broker_reuses_clients_and_closes_shared_pools():
    from mapping.sse_protocol import RedisStreamBroker
    assert "sync_client_factory" in inspect.signature(RedisStreamBroker).parameters, (
        "Redis shared client factories are not implemented"
    )

    class SyncClient:
        def incr(self, _key):
            return 1

        def expire(self, *_args):
            return True

        def xadd(self, *_args, **_kwargs):
            return "1-0"

        def close(self):
            self.closed = True

    class AsyncClient:
        async def aclose(self):
            self.closed = True

    sync_client = SyncClient()
    async_client = AsyncClient()
    sync_calls = []
    async_calls = []
    broker = RedisStreamBroker(
        "redis://test",
        sync_client_factory=lambda: sync_calls.append(True) or sync_client,
        async_client_factory=lambda: async_calls.append(True) or async_client,
    )

    broker.publish_sync("11", "process_log", {})
    broker.publish_sync("11", "process_log", {})
    broker._get_async_client()
    broker._get_async_client()
    broker.close()
    asyncio.run(broker.aclose())

    assert len(sync_calls) == 1
    assert len(async_calls) == 1
    assert sync_client.closed is True
    assert async_client.closed is True


def test_redis_broker_close_releases_async_pool_without_second_cleanup_call():
    from mapping.sse_protocol import RedisStreamBroker

    class SyncClient:
        def close(self):
            self.closed = True

    class AsyncClient:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    sync_client = SyncClient()
    async_client = AsyncClient()
    broker = RedisStreamBroker(
        "redis://test",
        sync_client_factory=lambda: sync_client,
        async_client_factory=lambda: async_client,
    )
    broker._get_sync_client()
    broker._get_async_client()

    broker.close()

    assert sync_client.closed is True
    assert async_client.closed is True


def test_sse_connection_lease_is_released_when_response_send_fails(monkeypatch):
    from mapping import sse

    app = sse.MapBuildSSEApplication()
    app.connection_budget = sse.SSEConnectionBudget(
        max_total=1, max_per_user=1, max_per_session=1
    )
    app._can_access_request = lambda *_args: _completed(True)

    class WaitingBroker:
        async def subscribe(self, *_args, **_kwargs):
            await asyncio.Event().wait()
            yield "never", "message", {}

    monkeypatch.setattr(sse, "get_event_broker", lambda: WaitingBroker())

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.body" and message["body"] == b": connected\n\n":
            raise RuntimeError("client write failed")

    with pytest.raises(RuntimeError, match="client write failed"):
        asyncio.run(
            app(
                {
                    "path": "/mapping/api/stream/11/",
                    "method": "GET",
                    "user": SimpleNamespace(is_authenticated=True, id=7),
                    "headers": [],
                },
                receive,
                send,
            )
        )

    assert app.connection_budget.acquire(user_id=7, session_id="user:7").acquired is True


def test_realtime_progress_events_are_coalesced_without_exposing_internal_key(monkeypatch):
    from mapping import realtime

    broker = sse_protocol.InMemoryEventBroker(coalesce_window_ms=200)
    monkeypatch.setattr(sse_protocol, "get_event_broker", lambda: broker)
    payload = {
        "type": "process_log",
        "request_id": 11,
        "step": "fetch",
        "message": "获取数据",
    }

    realtime.publish_map_build_event(11, payload)
    realtime.publish_map_build_event(11, payload)

    retained = broker.retained_events("11")
    assert len(retained) == 1
    assert "_coalesce_key" not in retained[0].payload


def test_realtime_progress_changes_are_not_dropped_by_coalescing(monkeypatch):
    from mapping import realtime

    broker = sse_protocol.InMemoryEventBroker(coalesce_window_ms=200)
    monkeypatch.setattr(sse_protocol, "get_event_broker", lambda: broker)
    first = {
        "type": "process_log",
        "request_id": 11,
        "step": "fetch",
        "message": "获取数据",
        "progress": 10,
    }
    second = dict(first, progress=20)

    realtime.publish_map_build_event(11, first)
    realtime.publish_map_build_event(11, second)

    retained = broker.retained_events("11")
    assert len(retained) == 2
    assert [event.payload["progress"] for event in retained] == [10, 20]


def test_redis_malformed_event_becomes_structured_stream_error():
    from mapping.sse_protocol import RedisStreamBroker

    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def xread(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.02)
                return [
                    (
                        "mapping:events:11",
                        [("1-0", {"event": "process_log", "payload": "{"})],
                    )
                ]
            return [
                (
                    "mapping:events:11",
                    [
                        (
                            "2-0",
                            {
                                "event": "done",
                                "payload": '{"request_id": 11, "status": "completed"}',
                            },
                        )
                    ],
                )
            ]

    broker = RedisStreamBroker("redis://test", async_client_factory=AsyncClient)

    async def scenario():
        return [
            event
            async for event in broker.subscribe_many(["11"], {})
        ]

    events = asyncio.run(scenario())
    assert events[0][2] == "stream_error"
    assert events[0][3]["error_code"] == "malformed_event"
    assert events[1][2] == "done"


def test_redis_stream_retries_after_read_failure(monkeypatch):
    from mapping.sse_protocol import RedisStreamBroker

    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def xread(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("redis temporarily unavailable")
            return [
                (
                    "mapping:events:11",
                    [
                        (
                            "2-0",
                            {
                                "event": "done",
                                "payload": '{"request_id": 11, "status": "completed"}',
                            },
                        )
                    ],
                )
            ]

    client = AsyncClient()
    broker = RedisStreamBroker(
        "redis://test", async_client_factory=lambda: client
    )

    original_sleep = asyncio.sleep

    async def no_delay(_delay):
        await original_sleep(0)

    monkeypatch.setattr("mapping.sse_protocol.asyncio.sleep", no_delay)

    async def scenario():
        stream = broker.subscribe_many(["11"], {}).__aiter__()
        try:
            first = await asyncio.wait_for(stream.__anext__(), timeout=1)
            second = await asyncio.wait_for(stream.__anext__(), timeout=1)
            return first, second
        finally:
            await stream.aclose()

    first, second = asyncio.run(scenario())

    assert client.calls >= 2
    assert first[2] == "stream_error"
    assert second[2] == "done"


def test_in_memory_subscription_cancellation_does_not_leave_blocked_worker_thread():
    broker = sse_protocol.InMemoryEventBroker()
    before = {thread.ident for thread in threading.enumerate()}

    async def scenario():
        iterator = broker.subscribe_many(["cancellation-check"], {}).__aiter__()
        task = asyncio.create_task(iterator.__anext__())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await iterator.aclose()

    asyncio.run(scenario())
    lingering = [
        thread
        for thread in threading.enumerate()
        if thread.ident not in before and thread.is_alive()
    ]
    assert not lingering


def test_redis_subscriber_receives_live_degraded_event_while_redis_is_healthy():
    from mapping.sse_protocol import RedisStreamBroker, get_default_broker

    class AsyncClient:
        async def xread(self, *_args, **_kwargs):
            await asyncio.sleep(0.05)
            return []

    broker = RedisStreamBroker("redis://test", async_client_factory=AsyncClient)
    fallback = get_default_broker()
    fallback._events.clear()
    fallback._next_ids.clear()

    async def scenario():
        stream = broker.subscribe_many(["99"], {})
        task = asyncio.create_task(stream.__anext__())
        await asyncio.sleep(0.01)
        fallback.publish_sync(
            "99",
            "request_failed",
            {"request_id": 99, "status": "failed", "transport_status": "degraded"},
        )
        result = await asyncio.wait_for(task, timeout=1)
        await stream.aclose()
        return result

    event = asyncio.run(scenario())
    assert event[0] == "99"
    assert event[2] == "request_failed"
    assert event[3]["transport_status"] == "degraded"


def test_redis_subscriber_does_not_replay_old_local_fallback_events():
    from mapping.sse_protocol import RedisStreamBroker, get_default_broker

    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def xread(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.02)
                return [
                    (
                        "mapping:events:99",
                        [("1-0", {"event": "process_log", "payload": '{"step":"redis"}'})],
                    )
                ]
            return [
                (
                    "mapping:events:99",
                    [("2-0", {"event": "done", "payload": '{"status":"completed"}'})],
                )
            ]

    fallback = get_default_broker()
    fallback._events.clear()
    fallback._next_ids.clear()
    fallback.publish_sync(
        "99",
        "process_log",
        {"request_id": 99, "step": "old-local", "transport_status": "degraded"},
    )
    broker = RedisStreamBroker("redis://test", async_client_factory=AsyncClient)

    async def scenario():
        return [event async for event in broker.subscribe_many(["99"], {})]

    events = asyncio.run(scenario())

    assert [event[2] for event in events] == ["process_log", "done"]
    assert events[0][3]["step"] == "redis"


def test_redis_subscriber_retries_after_a_temporary_read_failure():
    from mapping.sse_protocol import RedisStreamBroker, get_default_broker

    class AsyncClient:
        def __init__(self):
            self.calls = 0

        async def xread(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("redis disconnected")
            return [
                (
                    "mapping:events:100",
                    [("2-0", {"event": "done", "payload": '{"status":"completed"}'})],
                )
            ]

    fallback = get_default_broker()
    fallback._events.clear()
    fallback._next_ids.clear()
    client = AsyncClient()
    broker = RedisStreamBroker("redis://test", async_client_factory=lambda: client)

    async def scenario():
        return [event async for event in broker.subscribe_many(["100"], {})]

    events = asyncio.run(scenario())

    assert client.calls >= 2
    assert events[0][2] == "stream_error"
    assert events[-1][2] == "done"


def test_redis_cursor_gap_is_reported_before_replaying_retained_events():
    from mapping.sse_protocol import RedisStreamBroker

    class AsyncClient:
        async def xinfo_stream(self, _stream_key):
            return {"first-entry": ("5-0", {"event": "process_log"})}

        async def xread(self, *_args, **_kwargs):
            return [
                (
                    "mapping:events:101",
                    [
                        (
                            "5-0",
                            {
                                "event": "done",
                                "payload": '{"status":"completed"}',
                            },
                        )
                    ],
                )
            ]

    broker = RedisStreamBroker(
        "redis://test", async_client_factory=AsyncClient
    )

    async def scenario():
        return [
            event
            async for event in broker.subscribe_many(["101"], {"101": "1-0"})
        ]

    events = asyncio.run(scenario())

    assert events[0][2] == "stream_error"
    assert events[0][3]["error_code"] == "stream_cursor_gap"
    assert events[0][3]["next_action"] == "refresh_task_state"
    assert events[-1][2] == "done"


def test_realtime_fallback_keeps_progress_coalescing(monkeypatch):
    from mapping import realtime

    broker = sse_protocol.InMemoryEventBroker(coalesce_window_ms=200)
    monkeypatch.setattr(sse_protocol, "get_event_broker", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    payload = {
        "type": "process_log",
        "request_id": 11,
        "step": "fetch",
        "message": "获取数据",
    }
    default = sse_protocol.get_default_broker()
    default._events.clear()
    default._next_ids.clear()
    monkeypatch.setattr(realtime, "publish_map_build_event", realtime.publish_map_build_event)

    realtime.publish_map_build_event(11, payload)
    realtime.publish_map_build_event(11, payload)

    assert len(default.retained_events("11")) == 1


async def _completed(value):
    return value


def test_workbench_sse_budget_does_not_use_django_session_identity():
    from mapping.sse import MapBuildSSEApplication

    scope = {"session": SimpleNamespace(session_key="legacy-session-should-be-ignored")}
    assert MapBuildSSEApplication._session_id(scope, 7) == "user:7"
