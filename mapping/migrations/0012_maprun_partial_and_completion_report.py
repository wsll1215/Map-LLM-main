from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("mapping", "0011_maprun_trace_id")]

    operations = [
        migrations.AddField(
            model_name="maprequest",
            name="completion_report",
            field=models.JSONField(blank=True, default=dict, verbose_name="完成报告"),
        ),
        migrations.AddField(
            model_name="maprun",
            name="completion_report",
            field=models.JSONField(blank=True, default=dict, verbose_name="完成报告"),
        ),
    ]
