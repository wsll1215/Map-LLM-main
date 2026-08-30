"""ASGI Server-Sent Events endpoints for map-building progress."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qs

from channels.db import database_sync_to_async

from .sse_protocol import (
    TERMINAL_EVENTS,
    StreamRequestError,
    format_sse_event,
    get_event_broker,
    parse_stream_request,
    validate_stream_cursor,
)
from accounts.token_auth import access_token_expires_at


REQUEST_PATH = re.compile(r"^/mapping/api/stream/(?P<request_id>\d+)/?$")
SESSION_PATH = re.compile(r"^/mapping/api/stream/?$")
TERMINAL_REQUEST_STATUSES = {"completed", "partial", "failed", "needs_clarification"}
SSE_REAUTH_LEAD_SECONDS = 120


def should_reauthenticate(
    access_deadline: Any,
    *,
    now: Optional[float] = None,
    lead_seconds: Optional[float] = None,
) -> bool:
    if access_deadline is None:
        return False
    current_time = time.time() if now is None else float(now)
    lead = SSE_REAUTH_LEAD_SECONDS if lead_seconds is None else float(lead_seconds)
    return access_deadline.timestamp() - current_time <= lead


@dataclass
class SSEConnectionLease:
    acquired: bool
    error_code: Optional[str] = None
    retryable: bool = False
    next_action: Optional[str] = None
    _budget: Optional["SSEConnectionBudget"] = None
    _user_id: Optional[str] = None
    _session_id: Optional[str] = None
    _redis_client: Any = None
    _redis_keys: Optional[tuple] = None
    _redis_token: Optional[str] = None
    _released: bool = False

    def release(self) -> None:
        if self.acquired and not self._released and self._budget is not None:
            if self._redis_client is not None and self._redis_keys and self._redis_token:
                self._budget._release_redis(
                    self._redis_client, self._redis_keys, self._redis_token
                )
            else:
                self._budget._release(self._user_id, self._session_id)
            self._released = True

    def renew(self) -> None:
        if (
            self.acquired
            and not self._released
            and self._budget is not None
            and self._redis_client is not None
            and self._redis_keys
            and self._redis_token
        ):
            self._budget._renew_redis(
                self._redis_client, self._redis_keys, self._redis_token
            )


class SSEConnectionBudget:
    """Thread-safe per-process connection budget for long-lived SSE requests."""

    _REDIS_ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
for index = 1, 3 do
  redis.call('ZREMRANGEBYSCORE', KEYS[index], '-inf', now)
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return 0 end
if redis.call('ZCARD', KEYS[3]) >= tonumber(ARGV[5]) then return 0 end
local expires = now + ttl
for index = 1, 3 do redis.call('ZADD', KEYS[index], expires, ARGV[6]) end
return 1
"""
    _REDIS_RENEW_SCRIPT = """
local expires = tonumber(ARGV[1])
for index = 1, 3 do redis.call('ZADD', KEYS[index], expires, ARGV[2]) end
return 1
"""

    def __init__(
        self,
        *,
        max_total: int,
        max_per_user: int,
        max_per_session: int,
        redis_client: Any = None,
        lease_ttl_seconds: int = 60,
    ) -> None:
        self.max_total = max(0, int(max_total))
        self.max_per_user = max(0, int(max_per_user))
        self.max_per_session = max(0, int(max_per_session))
        self.redis_client = redis_client
        self.lease_ttl_seconds = max(10, int(lease_ttl_seconds))
        self._lock = threading.Lock()
        self._total = 0
        self._users: Dict[str, int] = {}
        self._sessions: Dict[str, int] = {}

    def acquire(self, *, user_id: Any, session_id: Any) -> SSEConnectionLease:
        user_key = str(user_id)
        session_key = str(session_id or f"user:{user_key}")
        if self.redis_client is not None:
            distributed = self._acquire_redis(user_key, session_key)
            if distributed is not None:
                return distributed
        return self._acquire_local(user_key, session_key)

    def _acquire_local(self, user_key: str, session_key: str) -> SSEConnectionLease:
        with self._lock:
            if self._total >= self.max_total:
                return self._limited()
            if self._users.get(user_key, 0) >= self.max_per_user:
                return self._limited()
            if self._sessions.get(session_key, 0) >= self.max_per_session:
                return self._limited()
            self._total += 1
            self._users[user_key] = self._users.get(user_key, 0) + 1
            self._sessions[session_key] = self._sessions.get(session_key, 0) + 1
        return SSEConnectionLease(
            acquired=True,
            _budget=self,
            _user_id=user_key,
            _session_id=session_key,
        )

    @staticmethod
    def _redis_keyset(user_key: str, session_key: str) -> tuple:
        prefix = "mapping:sse:{budget}"
        return (
            f"{prefix}:total",
            f"{prefix}:user:{user_key}",
            f"{prefix}:session:{session_key}",
        )

    def _acquire_redis(
        self, user_key: str, session_key: str
    ) -> Optional[SSEConnectionLease]:
        token = uuid.uuid4().hex
        keys = self._redis_keyset(user_key, session_key)
        try:
            allowed = self.redis_client.eval(
                self._REDIS_ACQUIRE_SCRIPT,
                len(keys),
                *keys,
                str(time.time()),
                str(self.lease_ttl_seconds),
                str(self.max_total),
                str(self.max_per_user),
                str(self.max_per_session),
                token,
            )
        except Exception:
            # A local fallback cannot enforce a global budget across workers.
            # Fail closed and let clients use REST polling until Redis recovers.
            return SSEConnectionLease(
                acquired=False,
                error_code="sse_budget_unavailable",
                retryable=True,
                next_action="poll_task_status",
            )
        if int(allowed or 0) != 1:
            return self._limited()
        return SSEConnectionLease(
            acquired=True,
            _budget=self,
            _user_id=user_key,
            _session_id=session_key,
            _redis_client=self.redis_client,
            _redis_keys=keys,
            _redis_token=token,
        )

    @staticmethod
    def _release_redis(client: Any, keys: tuple, token: str) -> None:
        try:
            for key in keys:
                client.zrem(key, token)
        except Exception:
            pass

    def _renew_redis(self, client: Any, keys: tuple, token: str) -> None:
        try:
            client.eval(
                self._REDIS_RENEW_SCRIPT,
                len(keys),
                *keys,
                str(time.time() + self.lease_ttl_seconds),
                token,
            )
        except Exception:
            pass

    def attach_redis_client(self, redis_client: Any) -> None:
        self.redis_client = redis_client

    @staticmethod
    def _limited() -> SSEConnectionLease:
        return SSEConnectionLease(
            acquired=False,
            error_code="sse_connection_limit",
            retryable=True,
            next_action="poll_task_status",
        )

    def _release(self, user_id: Optional[str], session_id: Optional[str]) -> None:
        with self._lock:
            self._total = max(0, self._total - 1)
            if user_id in self._users:
                self._users[user_id] -= 1
                if self._users[user_id] <= 0:
                    del self._users[user_id]
            if session_id in self._sessions:
                self._sessions[session_id] -= 1
                if self._sessions[session_id] <= 0:
                    del self._sessions[session_id]


def _setting(name: str, default: Any) -> Any:
    try:
        from django.conf import settings

        return getattr(settings, name, default)
    except Exception:
        return default


class MapBuildSSEApplication:
    """ASGI app for single-request and session-level multiplexed streams."""

    def __init__(self) -> None:
        self.heartbeat_seconds = float(_setting("MAP_SSE_HEARTBEAT_SECONDS", 15))
        self.max_requests = int(_setting("MAP_MAX_STREAM_REQUESTS", 20))
        self.connection_budget = SSEConnectionBudget(
            max_total=int(_setting("MAP_MAX_SSE_CONNECTIONS", 500)),
            max_per_user=int(_setting("MAP_MAX_SSE_CONNECTIONS_PER_USER", 4)),
            max_per_session=int(_setting("MAP_MAX_SSE_CONNECTIONS_PER_SESSION", 1)),
            lease_ttl_seconds=int(
                _setting("MAP_SSE_LEASE_TTL_SECONDS", max(60, int(self.heartbeat_seconds * 4)))
            ),
        )

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        single_match = REQUEST_PATH.match(scope.get("path", ""))
        session_match = SESSION_PATH.match(scope.get("path", ""))
        if not single_match and not session_match:
            await self._send_json(send, 404, {"error": "Not found"})
            return
        if scope.get("method", "GET").upper() != "GET":
            await self._send_json(send, 405, {"error": "SSE stream requires GET"})
            return

        user = scope.get("user")
        if not user or not user.is_authenticated:
            request_id = self._header(scope, "x-request-id")[:128] or uuid.uuid4().hex
            await self._send_json(
                send,
                401,
                {
                    "success": False,
                    "error": "Authentication required",
                    "error_code": "access_token_missing",
                    "retryable": False,
                    "next_action": "login",
                    "details": {},
                    "request_id": request_id,
                },
                headers=[(b"x-request-id", request_id.encode("utf-8"))],
            )
            return

        if single_match:
            request_keys = [single_match.group("request_id")]
            try:
                cursors = {request_keys[0]: validate_stream_cursor(self._event_cursor(scope))}
            except StreamRequestError as exc:
                await self._send_json(send, 400, exc.as_payload())
                return
            if not await self._can_access_request(user.id, int(request_keys[0])):
                await self._send_json(send, 403, {"error": "Forbidden"})
                return
            await self._stream_requests(
                scope,
                receive,
                send,
                user_id=user.id,
                request_keys=request_keys,
                cursors=cursors,
                multiplexed=False,
            )
            return

        try:
            request_keys, cursors = parse_stream_request(
                scope.get("query_string", b""), max_requests=self.max_requests
            )
        except StreamRequestError as exc:
            await self._send_json(send, 400, exc.as_payload())
            return
        request_ids = [int(request_key) for request_key in request_keys]
        if not await self._can_access_requests(user.id, request_ids):
            await self._send_json(send, 403, {"error": "Forbidden"})
            return
        await self._stream_requests(
            scope,
            receive,
            send,
            user_id=user.id,
            request_keys=request_keys,
            cursors=cursors,
            multiplexed=True,
        )

    async def _stream_requests(
        self,
        scope: Dict[str, Any],
        receive: Any,
        send: Any,
        *,
        user_id: Any,
        request_keys: List[str],
        cursors: Dict[str, str],
        multiplexed: bool,
    ) -> None:
        broker = get_event_broker()
        redis_client_factory = getattr(broker, "_get_sync_client", None)
        if callable(redis_client_factory) and self.connection_budget.redis_client is None:
            try:
                self.connection_budget.attach_redis_client(redis_client_factory())
            except Exception:
                pass
        lease = self.connection_budget.acquire(
            user_id=user_id, session_id=self._session_id(scope, user_id)
        )
        if not lease.acquired:
            await self._send_json(
                send,
                503 if lease.error_code == "sse_budget_unavailable" else 429,
                {
                    "success": False,
                    "error_code": lease.error_code,
                    "message": "实时连接数已达上限，当前使用任务状态同步",
                    "retryable": lease.retryable,
                    "next_action": lease.next_action,
                    "request_id": self._header(scope, "x-request-id")[:128] or uuid.uuid4().hex,
                    "details": {
                        "max_total": self.connection_budget.max_total,
                        "max_per_user": self.connection_budget.max_per_user,
                        "max_per_session": self.connection_budget.max_per_session,
                    },
                },
                headers=[(b"retry-after", b"5")],
            )
            return

        events = None
        disconnect_task = None
        event_task = None
        try:
            headers = [
                (b"content-type", b"text/event-stream; charset=utf-8"),
                (b"cache-control", b"no-cache, no-transform"),
                (b"connection", b"keep-alive"),
                (b"x-accel-buffering", b"no"),
            ]
            await send(
                {"type": "http.response.start", "status": 200, "headers": headers}
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b": connected\n\n",
                    "more_body": True,
                }
            )

            if multiplexed:
                events = broker.subscribe_many(request_keys, cursors)
            else:
                events = broker.subscribe(
                    request_keys[0], after_id=cursors.get(request_keys[0])
                )
            iterator = events.__aiter__()
            disconnect_task = asyncio.create_task(receive())
            event_task = asyncio.create_task(iterator.__anext__())
            active = set(request_keys)
            access_deadline = access_token_expires_at(scope.get("map_access_token", ""))
            while active:
                if should_reauthenticate(
                    access_deadline,
                    lead_seconds=_setting("MAP_SSE_REAUTH_LEAD_SECONDS", SSE_REAUTH_LEAD_SECONDS),
                ):
                    await self._send_reauth_events(
                        send,
                        active,
                        cursors,
                        multiplexed=multiplexed,
                    )
                    return
                completed, _ = await asyncio.wait(
                    {event_task, disconnect_task},
                    timeout=max(0.1, self.heartbeat_seconds),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not completed:
                    if should_reauthenticate(
                        access_deadline,
                        lead_seconds=_setting("MAP_SSE_REAUTH_LEAD_SECONDS", SSE_REAUTH_LEAD_SECONDS),
                    ):
                        await self._send_reauth_events(
                            send,
                            active,
                            cursors,
                            multiplexed=multiplexed,
                        )
                        return
                    terminal = await self._terminal_statuses(active, multiplexed)
                    for request_key, status in terminal.items():
                        if request_key not in active:
                            continue
                        payload = {
                            "request_id": int(request_key),
                            "status": status,
                            "stream_cursor": cursors.get(request_key) or "0-0",
                        }
                        is_last = len(active) == 1
                        await self._send_stream_event(
                            send,
                            request_key,
                            cursors.get(request_key) or "0-0",
                            "done",
                            payload,
                            multiplexed=multiplexed,
                            more_body=not is_last,
                        )
                        active.remove(request_key)
                        if is_last:
                            return
                    if not active:
                        return
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b": heartbeat\n\n",
                            "more_body": True,
                        }
                    )
                    lease.renew()
                    continue

                if disconnect_task in completed:
                    message = disconnect_task.result()
                    if message.get("type") == "http.disconnect":
                        return
                    disconnect_task = asyncio.create_task(receive())

                if event_task not in completed:
                    continue
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    return
                event_task = asyncio.create_task(iterator.__anext__())

                if multiplexed:
                    request_key, event_id, event_name, payload = event
                else:
                    request_key = request_keys[0]
                    event_id, event_name, payload = event
                if request_key not in active:
                    continue
                payload = dict(payload or {})
                payload.setdefault("request_id", int(request_key))
                payload.setdefault("stream_cursor", event_id)
                is_terminal = event_name in TERMINAL_EVENTS
                is_last = is_terminal and (not multiplexed or len(active) == 1)
                await self._send_stream_event(
                    send,
                    request_key,
                    event_id,
                    event_name,
                    payload,
                    multiplexed=multiplexed,
                    more_body=not is_last,
                )
                if is_terminal:
                    active.remove(request_key)
                if is_last:
                    return
        finally:
            for task in (event_task, disconnect_task):
                if task is not None and not task.done():
                    task.cancel()
            tasks = [task for task in (event_task, disconnect_task) if task is not None]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            close = getattr(events, "aclose", None) if events is not None else None
            if close is not None:
                await close()
            lease.release()

    async def _send_stream_event(
        self,
        send: Any,
        request_key: str,
        event_id: str,
        event_name: str,
        payload: Dict[str, Any],
        *,
        multiplexed: bool,
        more_body: bool,
    ) -> None:
        if multiplexed:
            payload.setdefault("stream_request_id", int(request_key))
            rendered_id = f"{request_key}:{event_id}"
        else:
            rendered_id = event_id
        rendered = format_sse_event(
            event_id=rendered_id, event_name=event_name, payload=payload
        )
        await send(
            {
                "type": "http.response.body",
                "body": rendered.encode("utf-8"),
                "more_body": more_body,
            }
        )

    async def _send_reauth_events(
        self,
        send: Any,
        active: Iterable[str],
        cursors: Dict[str, str],
        *,
        multiplexed: bool,
    ) -> None:
        active_keys = list(active)
        for index, request_key in enumerate(active_keys):
            cursor = cursors.get(request_key) or "0-0"
            await self._send_stream_event(
                send,
                request_key,
                cursor,
                "stream_reauth_required",
                {
                    "request_id": int(request_key),
                    "stream_cursor": cursor,
                    "error_code": "stream_reauth_required",
                    "retryable": True,
                    "next_action": "refresh_access_token",
                },
                multiplexed=multiplexed,
                more_body=index < len(active_keys) - 1,
            )

    async def _terminal_statuses(
        self, request_keys: Iterable[str], multiplexed: bool
    ) -> Dict[str, str]:
        if not multiplexed:
            key = next(iter(request_keys))
            status = await self._request_status(int(key))
            return {key: status} if status in TERMINAL_REQUEST_STATUSES else {}
        return {
            str(key): status
            for key, status in (
                await self._request_statuses([int(item) for item in request_keys])
            ).items()
            if status in TERMINAL_REQUEST_STATUSES
        }

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
    def _session_id(scope: Dict[str, Any], user_id: Any) -> str:
        # Workbench SSE is bearer-authenticated. Do not derive its connection
        # budget from Django's session cookie; sessions remain an admin concern.
        return f"user:{user_id}"

    @staticmethod
    async def _send_json(
        send: Any,
        status: int,
        payload: Dict[str, Any],
        *,
        headers: Optional[List[Any]] = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        response_headers = [(b"content-type", b"application/json; charset=utf-8")]
        response_headers.extend(headers or [])
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": response_headers,
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    @database_sync_to_async
    def _can_access_request(self, user_id: int, request_id: int) -> bool:
        from .models import MapRequest

        return MapRequest.objects.filter(id=request_id, user_id=user_id).exists()

    @database_sync_to_async
    def _can_access_requests(self, user_id: int, request_ids: List[int]) -> bool:
        from .models import MapRequest

        return MapRequest.objects.filter(
            id__in=request_ids, user_id=user_id
        ).count() == len(request_ids)

    @database_sync_to_async
    def _request_status(self, request_id: int) -> Optional[str]:
        from .models import MapRequest

        return (
            MapRequest.objects.filter(id=request_id)
            .values_list("status", flat=True)
            .first()
        )

    @database_sync_to_async
    def _request_statuses(self, request_ids: List[int]) -> Dict[int, Optional[str]]:
        from .models import MapRequest

        rows = MapRequest.objects.filter(id__in=request_ids).values_list("id", "status")
        return {request_id: status for request_id, status in rows}
