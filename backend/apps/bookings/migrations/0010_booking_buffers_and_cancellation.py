from django.core.validators import MaxValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('bookings', '0009_certifications')]

    operations = [
        migrations.AddField(
            model_name='bookablespace', name=name,
            field=models.PositiveIntegerField(default=0, validators=[MaxValueValidator(limit)]),
        )
        for name, limit in (
            ('buffer_before_minutes', 1440),
            ('buffer_after_minutes', 1440),
            ('cancellation_cutoff_hours', 8760),
        )
    ]
