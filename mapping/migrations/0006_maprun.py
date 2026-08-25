from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mapping', '0005_merge_20251025_1752'),
    ]

    operations = [
        migrations.CreateModel(
            name='MapRun',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('pending', '等待处理'),
                            ('running', '处理中'),
                            ('completed', '已完成'),
                            ('failed', '失败'),
                            ('cancel_requested', '取消中'),
                            ('cancelled', '已取消'),
                        ],
                        default='pending',
                        max_length=20,
                        verbose_name='运行状态',
                    ),
                ),
                (
                    'idempotency_key',
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        verbose_name='幂等键',
                    ),
                ),
                (
                    'map_version',
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        verbose_name='地图版本',
                    ),
                ),
                ('attempt', models.PositiveIntegerField(default=1, verbose_name='尝试次数')),
                (
                    'heartbeat_at',
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name='心跳时间',
                    ),
                ),
                (
                    'started_at',
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name='开始时间',
                    ),
                ),
                (
                    'finished_at',
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name='结束时间',
                    ),
                ),
                (
                    'error_code',
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name='错误代码',
                    ),
                ),
                ('error_message', models.TextField(blank=True, verbose_name='错误信息')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='创建时间')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                (
                    'request',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='runs',
                        to='mapping.maprequest',
                        verbose_name='关联请求',
                    ),
                ),
            ],
            options={
                'verbose_name': '地图运行',
                'verbose_name_plural': '地图运行',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='maprun',
            constraint=models.UniqueConstraint(
                fields=('request', 'idempotency_key'),
                name='mapping_run_request_idempotency_key_uniq',
            ),
        ),
    ]
