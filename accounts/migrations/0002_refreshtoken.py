from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="RefreshToken",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("token_hash", models.CharField(max_length=64, unique=True)),
                ("family_id", models.UUIDField(db_index=True, default=uuid.uuid4)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("idle_expires_at", models.DateTimeField()),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_reason", models.CharField(blank=True, max_length=100)),
                (
                    "remember_me",
                    models.BooleanField(default=False),
                ),
                ("user_agent", models.CharField(blank=True, max_length=512)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "replaced_by",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="replaced_token",
                        to="accounts.refreshtoken",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="refresh_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["user", "revoked_at"], name="accounts_re_user_id_4c5895_idx"),
                    models.Index(fields=["family_id", "revoked_at"], name="accounts_re_family__3aa20b_idx"),
                ],
            },
        ),
    ]
