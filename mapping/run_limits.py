"""Shared limits for long-running map executions."""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Any, Dict, Iterator, Optional

from django.conf import settings
from django.db import connection, transaction

from .models import MapRun


ACTIVE_RUN_STATUSES = (MapRun.STATUS_PENDING, MapRun.STATUS_RUNNING)

# Advisory locks are scoped to the current PostgreSQL transaction.  Keep the
# key stable across processes so every web worker serializes the same check.
ACTIVE_RUN_LOCK_KEY = 7_391_842_117
_PROCESS_ADMISSION_LOCK = RLock()


@contextmanager
def active_run_admission() -> Iterator[None]:
    """Serialize the capacity-check-to-create critical section.

    PostgreSQL uses a transaction-scoped advisory lock, while local SQLite
    development and unit tests use a process lock.  Callers must keep the
    context limited to admission and row creation; long-running work belongs
    outside it.
    """
    if connection.vendor == "postgresql":
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    [ACTIVE_RUN_LOCK_KEY],
                )
            yield
        return

    with _PROCESS_ADMISSION_LOCK:
        yield


def active_run_capacity_error(user_id: int) -> Optional[Dict[str, Any]]:
    """Return a structured limit error, or ``None`` when a run may start."""
    user_count = MapRun.objects.filter(
        request__user_id=user_id,
        status__in=ACTIVE_RUN_STATUSES,
    ).count()
    total_count = MapRun.objects.filter(status__in=ACTIVE_RUN_STATUSES).count()
    max_per_user = int(getattr(settings, "MAP_MAX_ACTIVE_RUNS_PER_USER", 3))
    max_total = int(getattr(settings, "MAP_MAX_ACTIVE_RUNS", 32))
    if user_count >= max_per_user:
        return {
            "success": False,
            "error_code": "active_run_limit_per_user",
            "message": "当前用户已有过多任务正在执行，请等待已有任务结束",
            "retryable": True,
            "next_action": "poll_task_status",
            "details": {
                "active_runs": user_count,
                "max_active_runs": max_per_user,
            },
        }
    if total_count >= max_total:
        return {
            "success": False,
            "error_code": "active_run_limit",
            "message": "系统当前执行任务已达上限，请稍后重试",
            "retryable": True,
            "next_action": "retry_later",
            "details": {
                "active_runs": total_count,
                "max_active_runs": max_total,
            },
        }
    return None
