from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0010_maprun_awaiting_input"),
    ]

    operations = [
        migrations.AddField(
            model_name="maprun",
            name="trace_id",
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name="智能体调用链标识",
            ),
        ),
    ]
