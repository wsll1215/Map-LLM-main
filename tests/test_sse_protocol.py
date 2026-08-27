import asyncio
import json
import sys
from types import SimpleNamespace

from mapping.sse_protocol import InMemoryEventBroker, format_sse_event


def test_format_sse_event_serializes_named_event_and_payload():
    rendered = format_sse_event(
        event_id="1-0",
        event_name="layer_upserted",
        payload={"request_id": 7, "ok": True},
    )

    assert rendered == (
        "id: 1-0\n"
        "event: layer_upserted\n"
        f"data: {json.dumps({'request_id': 7, 'ok': True}, ensure_ascii=False)}\n\n"
    )


def test_in_memory_broker_reads_events_after_last_id():
    async def scenario():
        broker = InMemoryEventBroker()
        first_id = await broker.publish("request-1", "request_started", {"step": 1})
        second_id = await broker.publish("request-1", "done", {"step": 2})

        events = [event async for event in broker.subscribe("request-1", after_id=first_id)]
        return first_id, second_id, events

    first_id, second_id, events = asyncio.run(scenario())

    assert first_id == "1"
    assert second_id == "2"
    assert events == [(second_id, "done", {"step": 2, "event_seq": 2})]


def test_in_memory_broker_adds_monotonic_event_sequence():
    async def scenario():
        broker = InMemoryEventBroker()
        await broker.publish("request-1", "request_started", {})
        await broker.publish("request-1", "done", {})
        return [event async for event in broker.subscribe("request-1")]

    events = asyncio.run(scenario())

    assert events[0][2]["event_seq"] == 1
    assert events[1][2]["event_seq"] == 2


def test_clarification_is_a_terminal_event():
    async def scenario():
        broker = InMemoryEventBroker()
        event_id = await broker.publish(
            "request-clarification",
            "request_needs_clarification",
            {"status": "needs_clarification"},
        )
        events = [event async for event in broker.subscribe("request-clarification")]
        return event_id, events

    event_id, events = asyncio.run(scenario())

    assert events == [
        (
            event_id,
            "request_needs_clarification",
            {"status": "needs_clarification", "event_seq": 1},
        )
    ]


def test_partial_is_a_terminal_request_status():
    from mapping.sse import TERMINAL_REQUEST_STATUSES

    assert "partial" in TERMINAL_REQUEST_STATUSES


def test_sse_stops_when_client_disconnects_before_next_event(monkeypatch):
    # Keep this transport test independent from GeoDjango's native libraries.
    monkeypatch.setitem(
        sys.modules,
        "mapping.models",
        SimpleNamespace(MapRequest=SimpleNamespace()),
    )
    from mapping import sse

    class WaitingBroker:
        async def subscribe(self, *_args, **_kwargs):
            await asyncio.Event().wait()
            yield "never", "message", {}

    async def scenario():
        app = sse.MapBuildSSEApplication()
        app._can_access_request = lambda *_args: _completed(True)
        app._request_status = lambda *_args: _completed("processing")
        monkeypatch.setattr(sse, "get_event_broker", lambda: WaitingBroker())
        messages = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        user = SimpleNamespace(is_authenticated=True, id=1)
        await asyncio.wait_for(
            app(
                {
                    "path": "/mapping/api/stream/123/",
                    "method": "GET",
                    "user": user,
                    "headers": [],
                },
                receive,
                send,
            ),
            timeout=0.5,
        )
        return messages

    async def _run():
        return await scenario()

    messages = asyncio.run(_run())
    assert len(messages) == 2
    assert messages[0]["type"] == "http.response.start"
    assert messages[1]["body"] == b": connected\n\n"
    assert messages[1]["more_body"] is True


def test_sse_uses_explicit_query_cursor_for_replayed_runs(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "mapping.models",
        SimpleNamespace(MapRequest=SimpleNamespace()),
    )
    from mapping import sse

    scope = {
        "path": "/mapping/api/stream/123/",
        "query_string": b"after=1787618097687-0",
        "headers": [],
    }

    assert sse.MapBuildSSEApplication._event_cursor(scope) == "1787618097687-0"


async def _completed(value):
    return value
