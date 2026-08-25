from django.core.management.base import BaseCommand

from gis_mapping_agent.data_sources import LocalDatasetCatalog
from mapping.models import Dataset


class Command(BaseCommand):
    help = "Scan local GIS files and refresh the dataset catalog."

    def add_arguments(self, parser):
        parser.add_argument("--root", default=None, help="Optional data root to scan")

    def handle(self, *args, **options):
        from pathlib import Path

        catalog = LocalDatasetCatalog(Path(options["root"]) if options["root"] else None)
        descriptors = catalog.scan()
        seen = set()
        for descriptor in descriptors:
            seen.add(descriptor.dataset_id)
            Dataset.objects.update_or_create(
                dataset_id=descriptor.dataset_id,
                defaults={
                    "name": descriptor.name,
                    "aliases": descriptor.aliases,
                    "source_type": descriptor.source_type,
                    "local_path": descriptor.local_path,
                    "geometry_type": descriptor.geometry_type,
                    "crs": descriptor.crs,
                    "bbox": descriptor.bbox,
                    "feature_count": descriptor.feature_count,
                    "status": Dataset.STATUS_AVAILABLE,
                    "metadata": descriptor.metadata,
                },
            )
        Dataset.objects.filter(source_type=Dataset.SOURCE_LOCAL).exclude(dataset_id__in=seen).update(
            status=Dataset.STATUS_FAILED,
            metadata={"error": "dataset file is no longer present"},
        )
        self.stdout.write(self.style.SUCCESS(f"Cataloged {len(descriptors)} local datasets."))
