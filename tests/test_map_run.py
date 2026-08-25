import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.contrib.auth import get_user_model

import django

django.setup()

from mapping.models import MapRequest, MapRun

pytestmark = pytest.mark.usefixtures("django_test_database")


def test_map_run_belongs_to_request_user():
    User = get_user_model()
    user = User.objects.create_user(username="run-owner", password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制北京地图")

    run = MapRun.objects.create(request=request, idempotency_key="request-1")

    assert run.request_id == request.id
    assert run.request.user_id == user.id
    assert run.status == MapRun.STATUS_PENDING


def test_map_run_keeps_agent_trace_id():
    User = get_user_model()
    user = User.objects.create_user(username="trace-owner", password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制北京地图")

    run = MapRun.objects.create(
        request=request,
        idempotency_key="trace-run",
        trace_id="web_session_1:create",
    )

    assert run.trace_id == "web_session_1:create"


def test_map_run_idempotency_key_is_unique_per_request():
    User = get_user_model()
    user = User.objects.create_user(username="idempotent-owner", password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制北京地图")
    MapRun.objects.create(request=request, idempotency_key="same-run")

    with pytest.raises(IntegrityError):
        MapRun.objects.create(request=request, idempotency_key="same-run")


def test_map_run_allows_only_forward_execution_states():
    User = get_user_model()
    user = User.objects.create_user(username="state-owner", password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制北京地图")
    run = MapRun.objects.create(request=request)

    run.transition_to(MapRun.STATUS_RUNNING)
    run.transition_to(MapRun.STATUS_CANCEL_REQUESTED)

    with pytest.raises(ValidationError):
        run.transition_to(MapRun.STATUS_COMPLETED)

    run.transition_to(MapRun.STATUS_CANCELLED)
    assert run.status == MapRun.STATUS_CANCELLED


def test_map_run_can_wait_for_clarification_without_being_completed():
    User = get_user_model()
    user = User.objects.create_user(username="clarification-run-owner", password="secret")
    request = MapRequest.objects.create(request_text="帮我画个图", user=user)
    run = MapRun.objects.create(request=request)

    run.transition_to(MapRun.STATUS_RUNNING)
    run.transition_to(MapRun.STATUS_AWAITING_INPUT)

    assert run.status == MapRun.STATUS_AWAITING_INPUT
    assert run.finished_at is not None


def test_map_run_rejects_unknown_state():
    User = get_user_model()
    user = User.objects.create_user(username="invalid-state-owner", password="secret")
    request = MapRequest.objects.create(user=user, request_text="绘制北京地图")
    run = MapRun.objects.create(request=request)

    with pytest.raises(ValidationError):
        run.transition_to("completed-by-client")
