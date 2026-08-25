from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0006_maprun"),
    ]

    operations = [
        migrations.CreateModel(
            name="Dataset",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("dataset_id", models.CharField(max_length=200, unique=True, verbose_name="数据集ID")),
                ("name", models.CharField(max_length=255, verbose_name="数据集名称")),
                ("aliases", models.JSONField(blank=True, default=list, verbose_name="名称别名")),
                ("source_type", models.CharField(choices=[("local", "本地数据"), ("remote", "远程数据"), ("upload", "用户上传")], default="local", max_length=20, verbose_name="数据来源类型")),
                ("source_url", models.URLField(blank=True, verbose_name="数据来源地址")),
                ("local_path", models.CharField(blank=True, max_length=500, verbose_name="本地相对路径")),
                ("geometry_type", models.CharField(blank=True, max_length=40, verbose_name="几何类型")),
                ("crs", models.CharField(blank=True, max_length=100, verbose_name="坐标系")),
                ("bbox", models.JSONField(blank=True, default=list, verbose_name="空间范围")),
                ("feature_count", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="要素数量")),
                ("license", models.CharField(blank=True, max_length=255, verbose_name="许可证")),
                ("checksum", models.CharField(blank=True, max_length=128, verbose_name="校验哈希")),
                ("version", models.CharField(default="1", max_length=100, verbose_name="数据版本")),
                ("status", models.CharField(choices=[("available", "可用"), ("pending", "处理中"), ("failed", "失败")], default="available", max_length=20, verbose_name="状态")),
                ("metadata", models.JSONField(blank=True, default=dict, verbose_name="数据元信息")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "数据集",
                "verbose_name_plural": "数据集",
                "ordering": ["name", "dataset_id"],
            },
        ),
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(fields=["source_type", "status"], name="mapping_dat_source__8aa6c2_idx"),
        ),
        migrations.AddIndex(
            model_name="dataset",
            index=models.Index(fields=["name"], name="mapping_dat_name_6eaf54_idx"),
        ),
    ]
