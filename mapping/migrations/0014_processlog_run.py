from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0013_auto_20260826_0026"),
    ]

    operations = [
        migrations.AddField(
            model_name="processlog",
            name="run",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="process_logs",
                to="mapping.maprun",
                verbose_name="关联运行",
            ),
        ),
    ]
