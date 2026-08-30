"""Opaque access and rotating refresh tokens for the map workbench."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import AuthAuditEvent, RefreshToken


ACCESS_TOKEN_TTL = int(getattr(settings, "MAP_AUTH_ACCESS_TTL_SECONDS", 600))
REFRESH_IDLE_TTL = int(getattr(settings, "MAP_AUTH_REFRESH_IDLE_SECONDS", 7 * 86400))
REFRESH_ABSOLUTE_TTL = int(getattr(settings, "MAP_AUTH_REFRESH_ABSOLUTE_SECONDS", 30 * 86400))
IDEMPOTENCY_TTL = int(getattr(settings, "MAP_AUTH_REFRESH_IDEMPOTENCY_SECONDS", 10))
REFRESH_COOKIE_NAME = getattr(settings, "MAP_AUTH_REFRESH_COOKIE_NAME", "map_refresh_token")


class TokenAuthError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = False,
        retry_after: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        next_action: Optional[str] = None,
        http_status: Optional[int] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after
        self.details = details or {}
        self.next_action = next_action or {
            "access_token_expired": "refresh_access_token",
            "refresh_temporarily_unavailable": "retry_refresh",
            "refresh_request_invalid": "retry_with_new_request_id",
            "auth_rate_limited": "wait",
        }.get(error_code, "login")
        self.http_status = http_status or {
            "refresh_request_invalid": 400,
            "refresh_temporarily_unavailable": 503,
            "auth_rate_limited": 429,
        }.get(error_code, 401)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: str
    refresh_expires_at: str
    remember_me: bool = False

    def public_payload(self) -> Dict[str, Any]:
        return {
            "success": True,
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TOKEN_TTL,
            "access_expires_at": self.access_expires_at,
            "refresh_expires_at": self.refresh_expires_at,
        }


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _access_cache_key(access_token: str) -> str:
    return f"map:auth:access:{_hash_token(access_token)}"


def _idempotency_cache_key(refresh_token: str, request_id: str) -> str:
    return f"map:auth:refresh:{_hash_token(refresh_token)}:{request_id}"


def _new_token() -> str:
    return secrets.token_urlsafe(48)


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception as exc:
        raise TokenAuthError(
            "refresh_temporarily_unavailable",
            "登录状态服务暂时不可用，请稍后重试",
            retryable=True,
            retry_after=1,
            details={"store": "token_cache"},
            http_status=503,
        ) from exc


def _cache_set(key: str, value: Any, timeout: int):
    try:
        cache.set(key, value, timeout=timeout)
    except Exception as exc:
        raise TokenAuthError(
            "refresh_temporarily_unavailable",
            "登录状态服务暂时不可用，请稍后重试",
            retryable=True,
            retry_after=1,
            details={"store": "token_cache"},
            http_status=503,
        ) from exc


def _issue_access_token(user_id: int, family_id: uuid.UUID) -> tuple[str, timezone.datetime]:
    access_token = _new_token()
    expires_at = timezone.now() + timedelta(seconds=ACCESS_TOKEN_TTL)
    _cache_set(
        _access_cache_key(access_token),
        {
            "user_id": user_id,
            "family_id": str(family_id),
            "expires_at": expires_at.isoformat(),
        },
        ACCESS_TOKEN_TTL,
    )
    return access_token, expires_at


def issue_token_pair(
    user: Any,
    *,
    remember_me: bool = False,
    user_agent: str = "",
    ip_address: Optional[str] = None,
) -> TokenPair:
    now = timezone.now()
    refresh_token = _new_token()
    refresh_expires_at = now + timedelta(seconds=REFRESH_ABSOLUTE_TTL)
    idle_expires_at = now + timedelta(seconds=REFRESH_IDLE_TTL)
    family_id = uuid.uuid4()
    RefreshToken.objects.create(
        user=user,
        token_hash=_hash_token(refresh_token),
        family_id=family_id,
        expires_at=refresh_expires_at,
        idle_expires_at=min(refresh_expires_at, idle_expires_at),
        remember_me=remember_me,
        user_agent=(user_agent or "")[:512],
        ip_address=ip_address,
    )
    access_token, access_expires_at = _issue_access_token(user.pk, family_id)
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at.isoformat(),
        refresh_expires_at=refresh_expires_at.isoformat(),
        remember_me=remember_me,
    )


def _pair_from_cache(value: Dict[str, Any]) -> TokenPair:
    return TokenPair(
        access_token=value["access_token"],
        refresh_token=value["refresh_token"],
        access_expires_at=value["access_expires_at"],
        refresh_expires_at=value["refresh_expires_at"],
        remember_me=bool(value.get("remember_me", False)),
    )


def rotate_refresh_token(
    raw_refresh_token: str,
    *,
    request_id: str,
    user_agent: str = "",
    ip_address: Optional[str] = None,
) -> TokenPair:
    if not raw_refresh_token:
        raise TokenAuthError("refresh_token_missing", "登录状态已失效，请重新登录")
    if not request_id or len(request_id) > 128:
        raise TokenAuthError("refresh_request_invalid", "刷新请求标识无效")

    cached = _cache_get(_idempotency_cache_key(raw_refresh_token, request_id))
    if cached:
        return _pair_from_cache(cached)

    now = timezone.now()
    pending_error = None
    pair = None
    with transaction.atomic():
        token = (
            RefreshToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=_hash_token(raw_refresh_token))
            .first()
        )
        if token is None:
            raise TokenAuthError("refresh_token_invalid", "登录状态已失效，请重新登录")

        cached = _cache_get(_idempotency_cache_key(raw_refresh_token, request_id))
        if cached:
            return _pair_from_cache(cached)

        if token.revoked_at is not None:
            if token.revoked_reason in {"rotated", "refresh_token_reuse_detected"}:
                _revoke_family(token.family_id, "refresh_token_reuse_detected")
                AuthAuditEvent.objects.create(
                    user=token.user,
                    event_type="refresh_token_reuse_detected",
                    family_id=token.family_id,
                    refresh_token_id=token.pk,
                    request_id=request_id[:128],
                    user_agent=(user_agent or token.user_agent)[:512],
                    ip_address=ip_address or token.ip_address,
                    details={"revoked_reason": token.revoked_reason},
                )
                pending_error = TokenAuthError(
                    "refresh_token_reuse_detected",
                    "检测到登录凭据重复使用，请重新登录",
                )
            elif token.revoked_reason == "refresh_token_expired":
                pending_error = TokenAuthError("refresh_token_expired", "登录状态已过期，请重新登录")
            else:
                pending_error = TokenAuthError("refresh_token_revoked", "登录状态已被撤销，请重新登录")
        elif token.expires_at <= now or token.idle_expires_at <= now:
            token.revoked_at = now
            token.revoked_reason = "refresh_token_expired"
            token.save(update_fields=["revoked_at", "revoked_reason"])
            pending_error = TokenAuthError("refresh_token_expired", "登录状态已过期，请重新登录")
        else:
            new_refresh_token = _new_token()
            new_refresh = RefreshToken.objects.create(
                user=token.user,
                token_hash=_hash_token(new_refresh_token),
                family_id=token.family_id,
                expires_at=token.expires_at,
                idle_expires_at=min(
                    token.expires_at,
                    now + timedelta(seconds=REFRESH_IDLE_TTL),
                ),
                remember_me=token.remember_me,
                user_agent=(user_agent or token.user_agent)[:512],
                ip_address=ip_address or token.ip_address,
            )
            token.revoked_at = now
            token.revoked_reason = "rotated"
            token.last_used_at = now
            token.replaced_by = new_refresh
            token.save(update_fields=["revoked_at", "revoked_reason", "last_used_at", "replaced_by"])
            access_token, access_expires_at = _issue_access_token(token.user_id, token.family_id)
            pair = TokenPair(
                access_token=access_token,
                refresh_token=new_refresh_token,
                access_expires_at=access_expires_at.isoformat(),
                refresh_expires_at=token.expires_at.isoformat(),
                remember_me=token.remember_me,
            )
            _cache_set(
                _idempotency_cache_key(raw_refresh_token, request_id),
                {
                    "access_token": pair.access_token,
                    "refresh_token": pair.refresh_token,
                    "access_expires_at": pair.access_expires_at,
                    "refresh_expires_at": pair.refresh_expires_at,
                    "remember_me": pair.remember_me,
                },
                IDEMPOTENCY_TTL,
            )
    if pending_error is not None:
        raise pending_error
    assert pair is not None
    return pair


def revoke_refresh_family(family_id: uuid.UUID, reason: str = "revoked") -> int:
    return _revoke_family(family_id, reason)


def _revoke_family(family_id: uuid.UUID, reason: str) -> int:
    return RefreshToken.objects.filter(family_id=family_id, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=reason
    )


def revoke_user_tokens(user: Any, reason: str = "user_revoked") -> int:
    return RefreshToken.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoked_reason=reason
    )


def authenticate_access_token(raw_access_token: str) -> Any:
    from django.contrib.auth import get_user_model

    if not raw_access_token:
        raise TokenAuthError("access_token_missing", "需要登录后继续")
    value = _cache_get(_access_cache_key(raw_access_token))
    if not value:
        raise TokenAuthError("access_token_expired", "访问凭据已过期", retryable=True)
    user = get_user_model().objects.filter(id=value.get("user_id"), is_active=True).first()
    if user is None:
        raise TokenAuthError("access_token_invalid", "登录状态无效")
    return user


def access_token_expires_at(raw_access_token: str) -> Optional[datetime]:
    """Return the cached opaque-token deadline for long-lived transports."""

    if not raw_access_token:
        return None
    try:
        value = _cache_get(_access_cache_key(raw_access_token))
    except TokenAuthError:
        return None
    raw_expires_at = value.get("expires_at") if isinstance(value, dict) else None
    if not raw_expires_at:
        return None
    try:
        return datetime.fromisoformat(str(raw_expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def revoke_access_token(raw_access_token: str) -> bool:
    """Revoke one opaque access token immediately, including on logout."""

    if not raw_access_token:
        return False
    return bool(cache.delete(_access_cache_key(raw_access_token)))
