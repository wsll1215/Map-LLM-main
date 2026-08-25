from mapping.task_dispatch import dispatch_task


def test_dispatch_task_uses_worker_when_available():
    calls = []

    result = dispatch_task(
        worker=lambda value: calls.append(("worker", value)) or "worker-id",
        fallback=lambda value: calls.append(("fallback", value)) or "thread-id",
        argument=7,
    )

    assert result == "worker-id"
    assert calls == [("worker", 7)]


def test_dispatch_task_uses_fallback_only_when_worker_is_unavailable():
    calls = []

    result = dispatch_task(
        worker=None,
        fallback=lambda value: calls.append(("fallback", value)) or "thread-id",
        argument=7,
    )

    assert result == "thread-id"
    assert calls == [("fallback", 7)]
