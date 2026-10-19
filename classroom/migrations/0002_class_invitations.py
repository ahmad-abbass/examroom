
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='join_enabled',
            field=models.BooleanField(default=True),
        ),
    ]
