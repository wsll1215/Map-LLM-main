from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("mapping", "0018_dedupe_terminal_trace_events")]

    operations = [
        migrations.AddField(
            model_name="maprun",
            name="source_plan",
            field=models.JSONField(blank=True, default=dict, verbose_name="来源计划诊断"),
        ),
    ]
