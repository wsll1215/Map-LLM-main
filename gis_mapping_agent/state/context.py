"""Lightweight per-session runtime context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class SessionContext:
    session_id: str
    task_id: str = field(default_factory=lambda: str(uuid4()))
    map_state: Optional[Any] = None
    generalization_result: Optional[Dict[str, Any]] = None
    generalization_params: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


class SessionContextStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._contexts: Dict[str, SessionContext] = {}

    def get(self, session_id: Optional[str], create: bool = True) -> Optional[SessionContext]:
        if not session_id:
            return None
        with self._lock:
            context = self._contexts.get(session_id)
            if context is None and create:
                context = SessionContext(session_id=session_id)
                self._contexts[session_id] = context
            return context

    def save_map_state(self, session_id: Optional[str], map_state: Any) -> Optional[SessionContext]:
        context = self.get(session_id, create=True)
        if context is None:
            return None
        context.map_state = map_state
        context.touch()
        return context

    def save_generalization(
        self,
        session_id: Optional[str],
        *,
        map_state: Any = None,
        generalization_result: Optional[Dict[str, Any]] = None,
        generalization_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionContext]:
        context = self.get(session_id, create=True)
        if context is None:
            return None
        if map_state is not None:
            context.map_state = map_state
        if generalization_result is not None:
            context.generalization_result = generalization_result
        if generalization_params is not None:
            context.generalization_params = generalization_params
        context.touch()
        return context

    def clear(self, session_id: Optional[str]) -> None:
        if not session_id:
            return
        with self._lock:
            self._contexts.pop(session_id, None)


_STORE = SessionContextStore()


def get_session_context(session_id: Optional[str], create: bool = True) -> Optional[SessionContext]:
    return _STORE.get(session_id, create=create)


def get_map_state_context(session_id: Optional[str], *, load_persisted: bool = True) -> Optional[Any]:
    """Return the session map state, hydrating it from SQLite when needed."""
    context = get_session_context(session_id, create=False)
    if context and context.map_state is not None:
        return context.map_state

    if not load_persisted or not session_id:
        return None

    from .manager import get_state_manager

    map_state = get_state_manager().load_state(session_id)
    if map_state is not None:
        save_map_state_context(session_id, map_state)
    return map_state


def get_generalization_context(session_id: Optional[str], *, load_persisted: bool = True) -> Optional[SessionContext]:
    """Return context populated with generalization state/result when available."""
    context = get_session_context(session_id, create=False)
    if context:
        if context.generalization_result is not None:
            return context
        if context.map_state is not None and getattr(context.map_state, "is_generalization_task", False):
            return context

    map_state = get_map_state_context(session_id, load_persisted=load_persisted)
    if map_state is None:
        return None

    if getattr(map_state, "is_generalization_task", False):
        return save_generalization_context(
            session_id,
            map_state=map_state,
            generalization_result=getattr(map_state, "generalization_result", None),
            generalization_params=getattr(map_state, "generalization_params", None),
        )

    return None


def get_generalization_state(session_id: Optional[str], *, load_persisted: bool = True):
    context = get_generalization_context(session_id, load_persisted=load_persisted)
    map_state = context.map_state if context else None
    result = context.generalization_result if context else None
    if result is None and map_state is not None:
        result = getattr(map_state, "generalization_result", None)
    return session_id, map_state, result


def save_map_state_context(session_id: Optional[str], map_state: Any) -> Optional[SessionContext]:
    return _STORE.save_map_state(session_id, map_state)


def save_generalization_context(
    session_id: Optional[str],
    *,
    map_state: Any = None,
    generalization_result: Optional[Dict[str, Any]] = None,
    generalization_params: Optional[Dict[str, Any]] = None,
) -> Optional[SessionContext]:
    return _STORE.save_generalization(
        session_id,
        map_state=map_state,
        generalization_result=generalization_result,
        generalization_params=generalization_params,
    )


def clear_session_context(session_id: Optional[str]) -> None:
    _STORE.clear(session_id)
