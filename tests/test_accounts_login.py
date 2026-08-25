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
