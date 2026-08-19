"""ASGI Server-Sent Events endpoint for map-building progress."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional

from channels.db import database_sync_to_async

from .models import MapRequest
from .sse_protocol import TERMINAL_EVENTS, format_sse_event, get_event_broker


REQUEST_PATH = re.compile(r"^/mapping/api/stream/(?P<request_id>\d+)/?$")


class MapBuildSSEApplication:
    """ASGI app that streams one authenticated MapRequest at a time."""

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        match = REQUEST_PATH.match(scope.get("path", ""))
        if not match:
            await self._send_json(send, 404, {"error": "Not found"})
            return

        if scope.get("method", "GET").upper() != "GET":
            await self._send_json(send, 405, {"error": "SSE stream requires GET"})
            return

        user = scope.get("user")
        request_id = int(match.group("request_id"))
        if not user or not user.is_authenticated:
            await self._send_json(send, 401, {"error": "Authentication required"})
            return
        if not await self._can_access_request(user.id, request_id):
            await self._send_json(send, 403, {"error": "Forbidden"})
            return

        headers = [
            (b"content-type", b"text/event-stream; charset=utf-8"),
            (b"cache-control", b"no-cache, no-transform"),
            (b"connection", b"keep-alive"),
            (b"x-accel-buffering", b"no"),
        ]
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b": connected\n\n", "more_body": True})

        after_id = self._header(scope, "last-event-id")
        broker = get_event_broker()
        events = broker.subscribe(str(request_id), after_id=after_id or None)
        iterator = events.__aiter__()
        try:
            while True:
                try:
                    event_id, event_name, payload = await asyncio.wait_for(
                        iterator.__anext__(), timeout=15
                    )
                except asyncio.TimeoutError:
                    status = await self._request_status(request_id)
                    if status in {"completed", "failed"}:
                        payload = {"request_id": request_id, "status": status}
                        rendered = format_sse_event(
                            event_id=f"status-{request_id}",
                            event_name="done",
                            payload=payload,
                        )
                        await send(
                            {
                                "type": "http.response.body",
                                "body": rendered.encode("utf-8"),
                                "more_body": False,
                            }
                        )
                        return
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b": heartbeat\n\n",
                            "more_body": True,
                        }
                    )
                    continue
                except StopAsyncIteration:
                    break

                rendered = format_sse_event(
                    event_id=event_id,
                    event_name=event_name,
                    payload=payload,
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": rendered.encode("utf-8"),
                        "more_body": event_name not in TERMINAL_EVENTS,
                    }
                )
                if event_name in TERMINAL_EVENTS:
                    return
        except asyncio.CancelledError:
            raise
        finally:
            close = getattr(events, "aclose", None)
            if close is not None:
                await close()

    @staticmethod
    def _header(scope: Dict[str, Any], name: str) -> str:
        target = name.lower().encode("ascii")
        for key, value in scope.get("headers", []):
            if key.lower() == target:
                return value.decode("utf-8", errors="ignore")
        return ""

    @staticmethod
    async def _send_json(send: Any, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @database_sync_to_async
    def _can_access_request(self, user_id: int, request_id: int) -> bool:
        return MapRequest.objects.filter(id=request_id, user_id=user_id).exists()

    @database_sync_to_async
    def _request_status(self, request_id: int) -> Optional[str]:
        return MapRequest.objects.filter(id=request_id).values_list("status", flat=True).first()
