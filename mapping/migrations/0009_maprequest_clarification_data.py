from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0008_datasetfeature"),
    ]

    operations = [
        migrations.AddField(
            model_name="maprequest",
            name="clarification_data",
            field=models.JSONField(blank=True, default=dict, verbose_name="澄清信息"),
        ),
        migrations.AlterField(
            model_name="maprequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "等待处理"),
                    ("processing", "处理中"),
                    ("needs_clarification", "等待补充信息"),
                    ("completed", "已完成"),
                    ("failed", "失败"),
                ],
                default="pending",
                max_length=20,
                verbose_name="状态",
            ),
        ),
    ]
