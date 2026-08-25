"""Dispatch long-running map work to a dedicated worker when configured."""

from threading import Thread
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


def dispatch_task(
    *,
    worker: Optional[Callable[[int], T]],
    fallback: Callable[[Any], T],
    argument: Any,
) -> T:
    """Use the external worker path when present, otherwise use local fallback."""
    return worker(argument) if worker is not None else fallback(argument)


def dispatch_map_request(map_request_id, run_id=None):
    from .tasks import process_map_request_task
    from .views import _process_map_request_in_background

    return dispatch_task(
        worker=(
            (lambda value: process_map_request_task.delay(value[0], value[1]))
            if process_map_request_task
            else None
        ),
        fallback=_start_thread(_process_map_request_in_background),
        argument=(map_request_id, run_id),
    )


def dispatch_conversation(
    map_request_id, message_text, run_id=None, include_clarification_context=False
):
    from .tasks import continue_conversation_task
    from .views import _continue_conversation_in_background

    return dispatch_task(
        worker=(
            (
                lambda value: continue_conversation_task.delay(
                    value[0], value[1], value[2], value[3]
                )
            )
            if continue_conversation_task
            else None
        ),
        fallback=_start_thread(_continue_conversation_in_background),
        argument=(map_request_id, message_text, run_id, include_clarification_context),
    )


def _start_thread(target):
    def start(argument):
        args = argument if isinstance(argument, tuple) else (argument,)
        thread = Thread(target=target, args=args, daemon=True)
        thread.start()
        return thread

    return start
