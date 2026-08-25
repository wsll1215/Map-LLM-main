import json
import math
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.contrib.gis.geos import WKBReader

from gis_mapping_agent.data_sources import LocalDatasetCatalog
from gis_mapping_agent.utils.config import Config
from mapping.models import Dataset, DatasetFeature


class Command(BaseCommand):
    help = "Import cataloged local GIS features into PostGIS."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default=None, help="Only import one dataset ID")
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--replace", action="store_true", help="Replace existing features")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("import_datasets_to_postgis 需要 PostgreSQL/PostGIS 主数据库")
        batch_size = max(1, min(options["batch_size"], 5000))
        catalog = LocalDatasetCatalog()
        descriptors = catalog.scan()
        if options["dataset"]:
            descriptors = [item for item in descriptors if item.dataset_id == options["dataset"]]
        if not descriptors:
            raise CommandError("没有找到可导入的数据集")

        imported = 0
        for descriptor in descriptors:
            dataset = Dataset.objects.filter(dataset_id=descriptor.dataset_id).first()
            if dataset is None:
                self.stderr.write(f"跳过未编目数据集: {descriptor.dataset_id}")
                continue
            count = self._import_one(dataset, descriptor.local_path, batch_size, options["replace"])
            imported += count
            self.stdout.write(f"{descriptor.dataset_id}: imported {count} features")
        self.stdout.write(self.style.SUCCESS(f"Imported {imported} features into PostGIS."))

    def _import_one(self, dataset, relative_path, batch_size, replace):
        import geopandas as gpd

        wkb_reader = WKBReader()
        path = (Config.DATA_DIRECTORY_BASE / relative_path).resolve()
        if Config.DATA_DIRECTORY_BASE.resolve() not in path.parents:
            raise CommandError(f"数据路径越界: {relative_path}")
        if not path.is_file():
            raise CommandError(f"数据文件不存在: {path}")
        frame = gpd.read_file(path)
        if frame.crs is None:
            raise CommandError(f"数据集没有 CRS，无法导入: {relative_path}")
        frame = frame.to_crs("EPSG:4326")
        rows = []
        with transaction.atomic():
            if replace:
                DatasetFeature.objects.filter(dataset=dataset).delete()
            for index, row in frame.iterrows():
                geometry = row.geometry
                if geometry is None or geometry.is_empty:
                    continue
                properties = {
                    str(key): self._json_safe(value)
                    for key, value in row.drop(labels=["geometry"], errors="ignore").items()
                }
                properties = json.loads(
                    json.dumps(properties, cls=DjangoJSONEncoder, allow_nan=False)
                )
                rows.append(
                    DatasetFeature(
                        dataset=dataset,
                        source_fid=str(index),
                        geom=wkb_reader.read(memoryview(geometry.wkb)),
                        properties=properties,
                    )
                )
                rows[-1].geom.srid = 4326
                if len(rows) >= batch_size:
                    DatasetFeature.objects.bulk_create(rows, batch_size=batch_size)
                    rows.clear()
            if rows:
                DatasetFeature.objects.bulk_create(rows, batch_size=batch_size)
            dataset.feature_count = DatasetFeature.objects.filter(dataset=dataset).count()
            dataset.save(update_fields=["feature_count", "updated_at"])
        return dataset.feature_count or 0

    @staticmethod
    def _json_safe(value):
        if value is None:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        try:
            import pandas as pd

            missing = pd.isna(value)
            if isinstance(missing, bool) and missing:
                return None
        except (TypeError, ValueError):
            pass
        if hasattr(value, "item"):
            return Command._json_safe(value.item())
        return value
