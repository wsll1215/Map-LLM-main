import json

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from accounts.middleware import token_auth_error_response
from accounts.models import AuthAuditEvent
from accounts.token_auth import TokenAuthError


pytestmark = pytest.mark.usefixtures("django_test_database")


def _login(client, username):
    response = client.post(
        "/accounts/api/tokens/",
        data=json.dumps({"username": username, "password": "correct horse battery staple"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    payload = response.json()
    return payload, response.cookies["map_refresh_token"].value


def test_password_login_returns_opaque_access_token_and_http_only_refresh_cookie():
    get_user_model().objects.create_user(
        username="token-login-owner",
        password="correct horse battery staple",
    )

    response = Client().post(
        "/accounts/api/tokens/",
        data=json.dumps(
            {
                "username": "token-login-owner",
                "password": "correct horse battery staple",
                "remember_me": False,
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["success"] is True
    assert payload["token_type"] == "Bearer"
    assert payload["expires_in"] == 600
    assert isinstance(payload["access_token"], str)
    assert len(payload["access_token"]) >= 40
    assert "refresh_token" not in payload
    assert response.cookies["map_refresh_token"]["httponly"] is True


def test_token_endpoint_validation_errors_include_request_context():
    response = Client().post(
        "/accounts/api/tokens/",
        data="not-json",
        content_type="application/json",
        HTTP_X_REQUEST_ID="request-login-validation-1",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error_code"] == "invalid_json"
    assert payload["request_id"] == "request-login-validation-1"
    assert response["X-Request-ID"] == "request-login-validation-1"


def test_token_login_accepts_the_legacy_no_trailing_slash_endpoint():
    username = "token-no-slash-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )

    response = Client().post(
        "/accounts/api/tokens",
        data=json.dumps({"username": username, "password": "correct horse battery staple"}),
        content_type="application/json",
    )

    assert response.status_code == 201
    assert response.json()["token_type"] == "Bearer"


def test_refresh_rotates_token_and_old_token_cannot_be_reused():
    username = "token-rotation-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    first_payload, first_refresh = _login(client, username)

    response = client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="refresh-request-1",
    )

    assert response.status_code == 200
    assert response.json()["access_token"] != first_payload["access_token"]
    second_refresh = response.cookies["map_refresh_token"].value
    assert second_refresh != first_refresh

    replay_client = Client()
    replay_client.cookies["map_refresh_token"] = first_refresh
    replay = replay_client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="refresh-request-replay",
    )

    assert replay.status_code == 401
    assert replay.json()["error_code"] == "refresh_token_reuse_detected"
    audit = AuthAuditEvent.objects.get(event_type="refresh_token_reuse_detected")
    assert audit.user.username == username
    assert audit.request_id == "refresh-request-replay"
    assert audit.details["revoked_reason"] == "rotated"


def test_revoked_refresh_token_is_distinguished_from_rotated_token_reuse():
    username = "token-revoked-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    payload, refresh_token = _login(client, username)

    logout = client.delete(
        "/accounts/api/tokens/current/",
        HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
    )
    assert logout.status_code == 200

    replay_client = Client()
    replay_client.cookies["map_refresh_token"] = refresh_token
    replay = replay_client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="refresh-after-logout",
    )

    assert replay.status_code == 401
    assert replay.json()["error_code"] == "refresh_token_revoked"


def test_delete_tokens_revokes_all_tokens_and_requires_bearer_authentication():
    username = "token-revoke-all-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    payload, refresh_token = _login(client, username)

    missing_auth = Client().delete("/accounts/api/tokens/")
    assert missing_auth.status_code == 401
    assert missing_auth.json()["error_code"] == "access_token_missing"

    response = client.delete(
        "/accounts/api/tokens/",
        HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
    )

    assert response.status_code == 200
    assert response.json()["revoked_refresh_tokens"] == 1
    assert client.get(
        "/mapping/api/map-requests/",
        HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
    ).status_code == 401

    replay_client = Client()
    replay_client.cookies["map_refresh_token"] = refresh_token
    replay = replay_client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="refresh-after-revoke-all",
    )
    assert replay.status_code == 401
    assert replay.json()["error_code"] == "refresh_token_revoked"


def test_repeated_refresh_request_id_returns_the_same_rotation_result():
    username = "token-refresh-idempotency-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    first_client = Client()
    _payload, first_refresh = _login(first_client, username)

    first_attempt = Client()
    first_attempt.cookies["map_refresh_token"] = first_refresh
    response_one = first_attempt.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="same-refresh-request",
    )

    retry_attempt = Client()
    retry_attempt.cookies["map_refresh_token"] = first_refresh
    response_two = retry_attempt.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="same-refresh-request",
    )

    assert response_one.status_code == 200
    assert response_two.status_code == 200
    assert response_two.json()["access_token"] == response_one.json()["access_token"]


def test_bearer_access_token_authorizes_map_api_without_django_session():
    username = "token-api-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    payload, _refresh = _login(client, username)

    response = client.get(
        "/mapping/api/map-requests/",
        HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_me_returns_authenticated_user_from_bearer_access_token():
    username = "token-me-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    payload, _refresh = _login(client, username)

    response = client.get(
        "/accounts/api/me/",
        HTTP_AUTHORIZATION=f"Bearer {payload['access_token']}",
    )

    assert response.status_code == 200
    assert response.json()["user"]["username"] == username


def test_session_cookie_cannot_authorize_workbench_api():
    user = get_user_model().objects.create_user(username="session-only-owner", password="secret")
    client = Client()
    client.force_login(user)

    response = client.get("/mapping/api/map-requests/")

    assert response.status_code == 401
    assert response.json()["error_code"] == "access_token_missing"


def test_logout_revokes_the_current_access_token_immediately():
    username = "logout-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    payload, _refresh = _login(client, username)
    headers = {"HTTP_AUTHORIZATION": f"Bearer {payload['access_token']}"}

    response = client.delete("/accounts/api/tokens/current/", **headers)

    assert response.status_code == 200
    assert client.get("/mapping/api/map-requests/", **headers).status_code == 401


def test_refresh_rejects_an_explicit_cross_origin_request():
    username = "origin-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    _login(client, username)

    response = client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="cross-origin-refresh",
        HTTP_ORIGIN="https://attacker.example",
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "csrf_origin_invalid"


def test_refresh_validation_error_has_structured_request_context():
    client = Client()

    response = client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REQUEST_ID="request-refresh-validation-1",
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "refresh_request_invalid"
    assert payload["request_id"] == "request-refresh-validation-1"
    assert payload["next_action"] == "retry_with_new_request_id"
    assert payload["details"] == {}


def test_refresh_cache_outage_is_retryable_and_structured(monkeypatch):
    username = "token-refresh-cache-outage-owner"
    get_user_model().objects.create_user(
        username=username,
        password="correct horse battery staple",
    )
    client = Client()
    _payload, _refresh = _login(client, username)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("accounts.token_auth.cache.get", unavailable)
    response = client.post(
        "/accounts/api/tokens/refresh/",
        HTTP_X_REFRESH_REQUEST_ID="refresh-cache-outage-1",
        HTTP_X_REQUEST_ID="request-refresh-outage-1",
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "refresh_temporarily_unavailable"
    assert payload["retryable"] is True
    assert payload["next_action"] == "retry_refresh"
    assert payload["request_id"] == "request-refresh-outage-1"
    assert payload["retry_after"] == 1


def test_bearer_error_response_preserves_retry_contract_and_request_id():
    response = token_auth_error_response(
        TokenAuthError(
            "refresh_temporarily_unavailable",
            "登录状态服务暂时不可用，请稍后重试",
            retryable=True,
            retry_after=2,
            details={"store": "token_cache"},
        ),
        request_id="request-middleware-1",
    )

    assert response.status_code == 503
    assert response["X-Request-ID"] == "request-middleware-1"
    assert response["Retry-After"] == "2"
    payload = json.loads(response.content)
    assert payload["request_id"] == "request-middleware-1"
    assert payload["details"] == {"store": "token_cache"}
    assert payload["next_action"] == "retry_refresh"
