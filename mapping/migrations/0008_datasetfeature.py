from django.contrib.gis.db import models as gis_models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0007_dataset"),
    ]

    operations = [
        migrations.CreateModel(
            name="DatasetFeature",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source_fid", models.CharField(max_length=255, verbose_name="源要素ID")),
                (
                    "geom",
                    gis_models.GeometryField(
                        dim=2,
                        spatial_index=True,
                        srid=4326,
                        verbose_name="几何",
                    ),
                ),
                ("properties", models.JSONField(blank=True, default=dict, verbose_name="属性")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="features",
                        to="mapping.dataset",
                        verbose_name="所属数据集",
                    ),
                ),
            ],
            options={
                "verbose_name": "数据集要素",
                "verbose_name_plural": "数据集要素",
            },
        ),
        migrations.AddConstraint(
            model_name="datasetfeature",
            constraint=models.UniqueConstraint(
                fields=("dataset", "source_fid"),
                name="mapping_dataset_feature_source_uniq",
            ),
        ),
    ]
