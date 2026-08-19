import asyncio
import json

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
    assert events == [(second_id, "done", {"step": 2})]
