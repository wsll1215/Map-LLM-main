from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("mapping", "0019_maprun_source_plan")]

    operations = [
        migrations.AddField(
            model_name="maprequest",
            name="creation_idempotency_key",
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                verbose_name="创建幂等键",
            ),
        ),
        migrations.AddField(
            model_name="chatmessage",
            name="client_message_id",
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                verbose_name="客户端消息ID",
            ),
        ),
        migrations.AddConstraint(
            model_name="maprequest",
            constraint=models.UniqueConstraint(
                fields=("user", "creation_idempotency_key"),
                name="mapping_request_user_creation_key_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="chatmessage",
            constraint=models.UniqueConstraint(
                fields=("request", "client_message_id"),
                name="mapping_message_request_client_id_uniq",
            ),
        ),
    ]
