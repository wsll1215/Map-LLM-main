from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_refreshtoken")]

    operations = [
        migrations.CreateModel(
            name="AuthAuditEvent",
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
                ("event_type", models.CharField(max_length=80)),
                ("family_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("refresh_token_id", models.BigIntegerField(blank=True, null=True)),
                ("request_id", models.CharField(blank=True, max_length=128)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=512)),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="auth_audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=("event_type", "created_at"), name="accounts_au_event_t_587947_idx"),
                    models.Index(fields=("user", "created_at"), name="accounts_au_user_id_a083da_idx"),
                ],
            },
        ),
    ]
