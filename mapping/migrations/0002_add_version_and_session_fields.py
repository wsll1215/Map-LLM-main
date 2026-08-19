# Generated migration file

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapping', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='generatedmap',
            name='version',
            field=models.PositiveIntegerField(default=1, verbose_name='版本号'),
        ),
        migrations.AddField(
            model_name='generatedmap',
            name='session_id',
            field=models.CharField(blank=True, max_length=100, verbose_name='会话ID'),
        ),
    ]

