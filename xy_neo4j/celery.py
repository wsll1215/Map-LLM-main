import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "xy_neo4j.settings")

app = Celery("map_llm")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
