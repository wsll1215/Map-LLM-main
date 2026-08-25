import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import django

django.setup()

from accounts.models import UserProfile
from mapping.models import MapRequest
from mapping.sse import MapBuildSSEApplication
from mapping.sse_protocol import get_event_broker


user = UserProfile.objects.get(username="codex-test")
request = MapRequest.objects.create(
    user=user, title="SSE check", request_text="test", status="completed"
)
broker = get_event_broker()
broker.publish_sync(str(request.id), "request_started", {"request_id": request.id})
broker.publish_sync(
    str(request.id), "done", {"request_id": request.id, "status": "completed"}
)


async def receive():
    return {"type": "http.disconnect"}


async def main():
    messages = []

    async def send(message):
        messages.append(message)

    await MapBuildSSEApplication()(
        {
            "path": f"/mapping/api/stream/{request.id}/",
            "method": "GET",
            "user": user,
            "headers": [],
        },
        receive,
        send,
    )
    body = b"".join(message.get("body", b"") for message in messages[1:]).decode()
    print("sse_status", messages[0]["status"])
    print("sse_frames", len(messages) - 1)
    print("has_request_started", "event: request_started" in body)
    print("has_done", "event: done" in body)


asyncio.run(main())
