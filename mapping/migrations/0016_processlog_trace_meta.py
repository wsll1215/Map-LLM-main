from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("mapping", "0015_processlog_trace_event")]

    operations = [
        migrations.AlterModelOptions(
            name="processlog",
            options={
                "ordering": ["created_at", "id"],
                "verbose_name": "处理日志",
                "verbose_name_plural": "处理日志",
            },
        ),
        migrations.RemoveIndex(
            model_name="processlog",
            name="mapping_pro_run_id_0d4a4f_idx",
        ),
        migrations.RemoveIndex(
            model_name="processlog",
            name="mapping_pro_run_id_18aa21_idx",
        ),
        migrations.AddIndex(
            model_name="processlog",
            index=models.Index(fields=["run", "event_seq"], name="mapping_pro_run_id_c20cf9_idx"),
        ),
        migrations.AddIndex(
            model_name="processlog",
            index=models.Index(fields=["run", "event_type", "status"], name="mapping_pro_run_id_d5dc6c_idx"),
        ),
    ]
