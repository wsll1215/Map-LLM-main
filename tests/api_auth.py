import json

from django.test import Client


def login_client(user, password="secret"):
    """Return a client authenticated through the workbench token API."""

    client = Client()
    response = client.post(
        "/accounts/api/tokens/",
        data=json.dumps(
            {
                "username": user.get_username(),
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    client.defaults["HTTP_AUTHORIZATION"] = (
        f"Bearer {response.json()['access_token']}"
    )
    return client
