
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0002_class_invitations'),
    ]

    operations = [
        migrations.AddField(
            model_name='answer',
            name='flagged',
            field=models.BooleanField(default=False),
        ),
    ]
