import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

django.setup()

pytestmark = pytest.mark.usefixtures("django_test_database")


def test_successful_login_redirects_to_mapping_workbench():
    get_user_model().objects.create_user(username="login-owner", password="secret")

    response = Client().post(
        "/accounts/login",
        {"username": "login-owner", "password": "secret"},
    )

    assert response.status_code == 302
    assert response["Location"] == "/mapping/"


def test_authenticated_user_visiting_login_is_sent_to_mapping_workbench():
    user = get_user_model().objects.create_user(username="already-authenticated", password="secret")
    client = Client()
    client.force_login(user)

    response = client.get("/accounts/login")

    assert response.status_code == 302
    assert response["Location"] == "/mapping/"


def test_login_page_accepts_trailing_slash():
    response = Client().get("/accounts/login/")

    assert response.status_code == 200


def test_login_route_returns_rendered_template_and_auth_stylesheet():
    response = Client().get("/accounts/login")

    assert response.status_code == 200
    assert b"{%" not in response.content
    assert b"{{" not in response.content
    assert b'name="csrfmiddlewaretoken"' in response.content
    assert b'href="/static/css/auth.css"' in response.content


def test_mapping_workbench_page_does_not_require_django_session():
    response = Client().get("/mapping/")

    assert response.status_code == 200


def test_login_remember_me_sets_persistent_refresh_cookie():
    get_user_model().objects.create_user(username="remember-owner", password="secret")

    response = Client().post(
        "/accounts/login",
        {"username": "remember-owner", "password": "secret", "remember_me": "on"},
    )

    assert response.status_code == 302
    assert response.cookies["map_refresh_token"]["max-age"] == 2592000
