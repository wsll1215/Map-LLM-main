import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

django.setup()

from mapping.models import ChatMessage, MapRequest, MapRun


pytestmark = pytest.mark.usefixtures("django_test_database")


def token_client(username):
    user = get_user_model().objects.create_user(username=username, password="secret")
    client = Client()
    response = client.post(
        "/accounts/api/tokens/",
        data=json.dumps({"username": username, "password": "secret"}),
        content_type="application/json",
    )
    assert response.status_code == 201
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {response.json()['access_token']}"
    return client, user


def test_rest_request_creation_replays_the_same_idempotent_request():
    client, user = token_client("request-idempotency-owner")
    headers = {"Idempotency-Key": "create-operation-1"}

    first = client.post(
        "/mapping/api/map-requests/",
        data=json.dumps({"request_text": "绘制城市道路"}),
        content_type="application/json",
        **{f"HTTP_{key.upper().replace('-', '_')}": value for key, value in headers.items()},
    )
    second = client.post(
        "/mapping/api/map-requests/",
        data=json.dumps({"request_text": "绘制城市道路"}),
        content_type="application/json",
        **{f"HTTP_{key.upper().replace('-', '_')}": value for key, value in headers.items()},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert MapRequest.objects.filter(user=user).count() == 1


def test_legacy_process_replays_a_started_run_after_a_lost_response(monkeypatch):
    client, user = token_client("process-idempotency-owner")
    map_request = MapRequest.objects.create(user=user, request_text="绘制道路")
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    dispatches = []
    monkeypatch.setattr(
        "mapping.views.dispatch_map_request",
        lambda *args: dispatches.append(args),
    )
    request_headers = {"HTTP_IDEMPOTENCY_KEY": "process-operation-1"}

    first = client.post(
        "/mapping/api/process-request/",
        data=json.dumps({"request_id": map_request.id}),
        content_type="application/json",
        **request_headers,
    )
    second = client.post(
        "/mapping/api/process-request/",
        data=json.dumps({"request_id": map_request.id}),
        content_type="application/json",
        **request_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
    assert MapRun.objects.filter(request=map_request).count() == 1
    assert len(dispatches) == 1


def test_conversation_replay_by_message_id_does_not_create_another_user_message(monkeypatch):
    client, user = token_client("message-idempotency-owner")
    map_request = MapRequest.objects.create(
        user=user,
        request_text="绘制道路",
        status="completed",
    )
    monkeypatch.setattr("mapping.views.MAP_LLM_AVAILABLE", True)
    monkeypatch.setattr("mapping.views.dispatch_conversation", lambda *_args: None)
    payload = json.dumps({"request_id": map_request.id, "message": "补充主干道"})

    first = client.post(
        "/mapping/api/continue-conversation/",
        data=payload,
        content_type="application/json",
        HTTP_X_MESSAGE_ID="message-operation-1",
    )
    second = client.post(
        "/mapping/api/continue-conversation/",
        data=payload,
        content_type="application/json",
        HTTP_X_MESSAGE_ID="message-operation-1",
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert ChatMessage.objects.filter(
        request=map_request,
        client_message_id="message-operation-1",
    ).count() == 1
