from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapping', '0012_maprun_partial_and_completion_report'),
    ]

    operations = [
        migrations.CreateModel(
            name='MainDatabase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='Django 主数据库', max_length=255, verbose_name='数据库名称')),
                ('db_type', models.CharField(default='main', editable=False, max_length=50)),
            ],
            options={
                'verbose_name': 'Django主数据库',
                'verbose_name_plural': 'Django主数据库',
                'db_table': 'mapping_maindatabase',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='MapStatesDatabase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(default='地图状态数据库', max_length=255, verbose_name='数据库名称')),
                ('db_type', models.CharField(default='map_states', editable=False, max_length=50)),
            ],
            options={
                'verbose_name': '地图状态数据库',
                'verbose_name_plural': '地图状态数据库',
                'db_table': 'mapping_mapstatesdatabase',
                'managed': False,
            },
        ),
        migrations.RemoveIndex(
            model_name='dataset',
            name='mapping_dat_source__8aa6c2_idx',
        ),
        migrations.RemoveIndex(
            model_name='dataset',
            name='mapping_dat_name_6eaf54_idx',
        ),
        migrations.AlterField(
            model_name='maprequest',
            name='status',
            field=models.CharField(choices=[('pending', '等待处理'), ('processing', '处理中'), ('needs_clarification', '等待补充信息'), ('completed', '已完成'), ('partial', '部分完成'), ('failed', '失败')], default='pending', max_length=20, verbose_name='状态'),
        ),
        migrations.AlterField(
            model_name='maprun',
            name='status',
            field=models.CharField(choices=[('pending', '等待处理'), ('running', '处理中'), ('awaiting_input', '等待补充信息'), ('completed', '已完成'), ('partial', '部分完成'), ('failed', '失败'), ('cancel_requested', '取消中'), ('cancelled', '已取消')], default='pending', max_length=20, verbose_name='运行状态'),
        ),
        migrations.AddIndex(
            model_name='dataset',
            index=models.Index(fields=['source_type', 'status'], name='mapping_dat_source__20d40f_idx'),
        ),
        migrations.AddIndex(
            model_name='dataset',
            index=models.Index(fields=['name'], name='mapping_dat_name_464118_idx'),
        ),
    ]
