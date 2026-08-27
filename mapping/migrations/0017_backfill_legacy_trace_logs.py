from django.db import migrations, transaction


def bind_legacy_logs(apps, schema_editor):
    map_request_model = apps.get_model("mapping", "MapRequest")
    map_run_model = apps.get_model("mapping", "MapRun")
    process_log_model = apps.get_model("mapping", "ProcessLog")

    for map_request in map_request_model.objects.all().iterator():
        run = (
            map_run_model.objects.filter(request_id=map_request.pk)
            .order_by("-created_at", "-id")
            .first()
        )
        if run is None:
            continue

        with transaction.atomic():
            if not run.trace_id:
                run.trace_id = f"web_session_{map_request.pk}:legacy"
                run.save(update_fields=["trace_id"])

            orphaned = list(
                process_log_model.objects.filter(
                    request_id=map_request.pk,
                    run__isnull=True,
                ).order_by("created_at", "id")
            )
            if not orphaned:
                continue

            last_seq = max(
                process_log_model.objects.filter(run_id=run.pk).values_list(
                    "event_seq", flat=True
                ),
                default=0,
            )
            for offset, event in enumerate(orphaned, start=1):
                event.run_id = run.pk
                event.trace_id = run.trace_id
                event.event_seq = last_seq + offset
                event.phase = event.phase or event.step
                event.started_at = event.started_at or event.created_at
            process_log_model.objects.bulk_update(
                orphaned,
                ["run", "trace_id", "event_seq", "phase", "started_at"],
            )


class Migration(migrations.Migration):
    dependencies = [("mapping", "0016_processlog_trace_meta")]

    operations = [migrations.RunPython(bind_legacy_logs, migrations.RunPython.noop)]
