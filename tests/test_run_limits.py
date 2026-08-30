from contextlib import contextmanager


def test_active_run_admission_serializes_postgres_capacity_checks(monkeypatch):
    from django.db import connection

    from mapping import run_limits

    calls = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, params):
            calls.append((statement, params))

    @contextmanager
    def atomic():
        yield

    monkeypatch.setattr(connection, "vendor", "postgresql")
    monkeypatch.setattr(connection, "cursor", lambda: Cursor())
    monkeypatch.setattr(run_limits.transaction, "atomic", atomic)

    with run_limits.active_run_admission():
        pass

    assert calls == [
        ("SELECT pg_advisory_xact_lock(%s)", [run_limits.ACTIVE_RUN_LOCK_KEY])
    ]
