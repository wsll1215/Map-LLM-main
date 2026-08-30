from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid


# Create your models here.
class UserProfile(AbstractUser):
    mpassword = models.CharField(verbose_name='密码', blank=True, null=True, default='0', max_length=100)

    def __str__(self):
        return self.username

    class Meta:
        ordering = ['-id']
        verbose_name = '用户管理'
        verbose_name_plural = verbose_name


class RefreshToken(models.Model):
    """Rotating refresh-token family; raw tokens never live in the database."""

    user = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    family_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    idle_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=100, blank=True)
    replaced_by = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_token",
    )
    remember_me = models.BooleanField(default=False)
    user_agent = models.CharField(max_length=512, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("user", "revoked_at"),
                name="accounts_re_user_id_4c5895_idx",
            ),
            models.Index(
                fields=("family_id", "revoked_at"),
                name="accounts_re_family__3aa20b_idx",
            ),
        ]

    def __str__(self):
        return f"refresh:{self.user_id}:{self.family_id}"


class AuthAuditEvent(models.Model):
    """Security-relevant authentication events without raw token material."""

    user = models.ForeignKey(
        UserProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_audit_events",
    )
    event_type = models.CharField(max_length=80)
    family_id = models.UUIDField(null=True, blank=True, db_index=True)
    refresh_token_id = models.BigIntegerField(null=True, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=("event_type", "created_at")),
            models.Index(fields=("user", "created_at")),
        ]

    def __str__(self):
        return f"{self.event_type}:{self.request_id or self.id}"
