"""Bearer authentication for the token-only workbench APIs."""

from __future__ import annotations

import uuid

from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse

from .token_auth import TokenAuthError, authenticate_access_token


WORKBENCH_API_PREFIX = "/mapping/api/"
ACCOUNT_API_PREFIX = "/accounts/api/"
TOKEN_ENDPOINTS = {
    "/accounts/api/tokens/",
    "/accounts/api/tokens/refresh/",
    "/accounts/api/tokens/current/",
}


def _authorization_token(request):
    value = request.META.get("HTTP_AUTHORIZATION", "").strip()
    scheme, separator, token = value.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def token_auth_error_response(error: TokenAuthError, request_id: str | None = None):
    resolved_request_id = request_id or uuid.uuid4().hex
    response = JsonResponse(
        {
            "success": False,
            "error_code": error.error_code,
            "message": error.message,
            "retryable": error.retryable,
            "next_action": error.next_action,
            "retry_after": error.retry_after,
            "details": error.details,
            "request_id": resolved_request_id,
        },
        status=error.http_status or 401,
    )
    response["WWW-Authenticate"] = 'Bearer realm="map-workbench"'
    response["X-Request-ID"] = resolved_request_id
    if error.retry_after is not None:
        response["Retry-After"] = str(error.retry_after)
    return response


class WorkbenchBearerMiddleware:
    """Require Bearer auth for workbench APIs and never trust sessionid there."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not self._requires_bearer(request):
            return self.get_response(request)

        raw_token = _authorization_token(request)
        if not raw_token:
            return token_auth_error_response(
                TokenAuthError("access_token_missing", "需要登录后继续"),
                request.headers.get("X-Request-ID"),
            )
        try:
            request.user = authenticate_access_token(raw_token)
        except TokenAuthError as error:
            return token_auth_error_response(error, request.headers.get("X-Request-ID"))
        request.map_access_token = raw_token
        return self.get_response(request)

    @staticmethod
    def _requires_bearer(request):
        path = request.path
        normalized_path = path.rstrip("/") + "/"
        if path.startswith(WORKBENCH_API_PREFIX):
            return True
        if normalized_path == "/accounts/api/tokens/" and request.method.upper() == "DELETE":
            return True
        return path.startswith(ACCOUNT_API_PREFIX) and normalized_path not in TOKEN_ENDPOINTS


class WorkbenchBearerASGIMiddleware:
    """Inject the same Bearer-authenticated user into the SSE ASGI scope."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not scope.get("path", "").startswith(WORKBENCH_API_PREFIX + "stream"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        value = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
        scheme, separator, raw_token = value.partition(" ")
        if not separator or scheme.lower() != "bearer" or not raw_token.strip():
            await self._send_error(
                send,
                TokenAuthError("access_token_missing", "需要登录后继续"),
                self._request_id(scope),
            )
            return

        try:
            from channels.db import database_sync_to_async

            user = await database_sync_to_async(authenticate_access_token)(
                raw_token.strip()
            )
        except TokenAuthError as error:
            await self._send_error(send, error, self._request_id(scope))
            return

        scope = dict(scope)
        scope["user"] = user
        scope["map_access_token"] = raw_token.strip()
        await self.app(scope, receive, send)

    @staticmethod
    def _request_id(scope):
        headers = dict(scope.get("headers", []))
        raw_request_id = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore").strip()
        return raw_request_id[:128] or uuid.uuid4().hex

    @staticmethod
    async def _send_error(send, error, request_id):
        import json

        body = json.dumps(
            {
                "success": False,
                "error_code": error.error_code,
                "message": error.message,
                "retryable": error.retryable,
                "next_action": error.next_action,
                "retry_after": error.retry_after,
                "details": error.details,
                "request_id": request_id,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": error.http_status or 401,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"www-authenticate", b'Bearer realm="map-workbench"'),
                    (b"x-request-id", request_id.encode("utf-8")),
                    *(
                        [(b"retry-after", str(error.retry_after).encode("ascii"))]
                        if error.retry_after is not None
                        else []
                    ),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
