
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0003_answer_review_flags'),
    ]

    operations = [
        migrations.AddField(
            model_name='attempt',
            name='grading_revision',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
