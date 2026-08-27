from django.db import migrations, models
import mapping.models
import uuid


def populate_event_ids(apps, schema_editor):
    process_log = apps.get_model("mapping", "ProcessLog")
    for row in process_log.objects.all().only("pk"):
        row.event_id = f"evt_{uuid.uuid4().hex}"
        row.save(update_fields=["event_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0014_processlog_run"),
    ]

    operations = [
        migrations.AddField(
            model_name="processlog",
            name="actor",
            field=models.CharField(default="system", max_length=40, verbose_name="执行者"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="attributes",
            field=models.JSONField(blank=True, default=dict, verbose_name="事件属性"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="duration_ms",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="耗时毫秒"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="error",
            field=models.JSONField(blank=True, default=None, null=True, verbose_name="结构化错误"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="event_id",
            field=models.CharField(default=mapping.models._new_trace_event_id, max_length=80),
        ),
        migrations.AddField(
            model_name="processlog",
            name="event_seq",
            field=models.PositiveIntegerField(default=0, verbose_name="Trace序号"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="event_type",
            field=models.CharField(default="process_log", max_length=40, verbose_name="事件类型"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="finished_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="结束时间"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="input_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="结构化输入"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="output_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="结构化输出"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="parent_event_id",
            field=models.CharField(blank=True, max_length=80, verbose_name="父事件ID"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="phase",
            field=models.CharField(blank=True, max_length=60, verbose_name="业务阶段"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="开始时间"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="status",
            field=models.CharField(default="success", max_length=30, verbose_name="事件状态"),
        ),
        migrations.AddField(
            model_name="processlog",
            name="trace_id",
            field=models.CharField(blank=True, max_length=255, verbose_name="Trace ID"),
        ),
        migrations.RunPython(populate_event_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="processlog",
            name="event_id",
            field=models.CharField(default=mapping.models._new_trace_event_id, max_length=80, unique=True),
        ),
        migrations.AddIndex(
            model_name="processlog",
            index=models.Index(fields=["run", "event_seq"], name="mapping_pro_run_id_0d4a4f_idx"),
        ),
        migrations.AddIndex(
            model_name="processlog",
            index=models.Index(fields=["run", "event_type", "status"], name="mapping_pro_run_id_18aa21_idx"),
        ),
    ]
