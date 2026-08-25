from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mapping", "0009_maprequest_clarification_data"),
    ]

    operations = [
        migrations.AlterField(
            model_name="maprun",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "等待处理"),
                    ("running", "处理中"),
                    ("awaiting_input", "等待补充信息"),
                    ("completed", "已完成"),
                    ("failed", "失败"),
                    ("cancel_requested", "取消中"),
                    ("cancelled", "已取消"),
                ],
                default="pending",
                max_length=20,
                verbose_name="运行状态",
            ),
        ),
    ]
