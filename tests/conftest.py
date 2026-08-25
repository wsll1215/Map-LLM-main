import os

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

import django

django.setup()


@pytest.fixture(scope="session")
def django_test_database():
    from django.db import connection
    from django.test.utils import setup_test_environment, teardown_test_environment

    setup_test_environment()
    old_config = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    yield
    connection.creation.destroy_test_db(old_config, verbosity=0)
    teardown_test_environment()


@pytest.fixture(autouse=True)
def disable_background_map_dispatch(monkeypatch):
    """Keep API tests deterministic; worker dispatch has its own unit tests."""
    monkeypatch.setattr("mapping.rest_api.dispatch_map_request", lambda *args: None)
    yield
