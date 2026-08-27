"""ASGI Server-Sent Events endpoint for map-building progress."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qs

from channels.db import database_sync_to_async

from .models import MapRequest
from .sse_protocol import TERMINAL_EVENTS, format_sse_event, get_event_broker


REQUEST_PATH = re.compile(r"^/mapping/api/stream/(?P<request_id>\d+)/?$")
TERMINAL_REQUEST_STATUSES = {"completed", "partial", "failed", "needs_clarification"}


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

        after_id = self._event_cursor(scope)
        broker = get_event_broker()
        events = broker.subscribe(str(request_id), after_id=after_id or None)
        iterator = events.__aiter__()
        disconnect_task = asyncio.create_task(receive())
        event_task = asyncio.create_task(iterator.__anext__())
        try:
            while True:
                completed, _ = await asyncio.wait(
                    {event_task, disconnect_task},
                    timeout=15,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not completed:
                    status = await self._request_status(request_id)
                    if status in TERMINAL_REQUEST_STATUSES:
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

                if disconnect_task in completed:
                    message = disconnect_task.result()
                    if message.get("type") == "http.disconnect":
                        return
                    disconnect_task = asyncio.create_task(receive())

                if event_task not in completed:
                    continue

                try:
                    event_id, event_name, payload = event_task.result()
                except StopAsyncIteration:
                    return
                event_task = asyncio.create_task(iterator.__anext__())

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
            for task in (event_task, disconnect_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(event_task, disconnect_task, return_exceptions=True)
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

    @classmethod
    def _event_cursor(cls, scope: Dict[str, Any]) -> str:
        """Read the explicit cursor first so proxies cannot replay an old run."""
        query_string = scope.get("query_string", b"")
        if isinstance(query_string, bytes):
            query_string = query_string.decode("ascii", errors="ignore")
        query_cursor = parse_qs(query_string).get("after", [""])[0]
        return query_cursor or cls._header(scope, "last-event-id")

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
