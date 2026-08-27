from django.db import migrations, transaction


def dedupe_terminal_events(apps, schema_editor):
    map_run_model = apps.get_model("mapping", "MapRun")
    process_log_model = apps.get_model("mapping", "ProcessLog")

    for run in map_run_model.objects.all().iterator():
        with transaction.atomic():
            events = list(
                process_log_model.objects.filter(
                    run_id=run.pk,
                    event_type="run_finished",
                ).order_by("event_seq", "id")
            )
            for duplicate in events[1:]:
                duplicate.delete()

            remaining = list(
                process_log_model.objects.filter(run_id=run.pk).order_by("event_seq", "id")
            )
            changed = []
            for sequence, event in enumerate(remaining, start=1):
                if event.event_seq != sequence:
                    event.event_seq = sequence
                    changed.append(event)
            if changed:
                process_log_model.objects.bulk_update(changed, ["event_seq"])


class Migration(migrations.Migration):
    dependencies = [("mapping", "0017_backfill_legacy_trace_logs")]

    operations = [migrations.RunPython(dedupe_terminal_events, migrations.RunPython.noop)]
