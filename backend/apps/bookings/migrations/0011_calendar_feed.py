from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('bookings', '0010_booking_buffers_and_cancellation'), ('makerspaces', '0085_space_pack_profile'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='booking', name='calendar_sequence', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='booking', name='calendar_updated_at', field=models.DateTimeField(default=timezone.now)),
        migrations.CreateModel(name='BookingCalendarFeed', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('token_digest', models.BinaryField(max_length=32, unique=True)),
            ('token_hint', models.CharField(max_length=8)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('rotated_at', models.DateTimeField(blank=True, null=True)),
            ('revoked_at', models.DateTimeField(blank=True, null=True)),
            ('makerspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='makerspaces.makerspace')),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        ], options={'constraints': [models.UniqueConstraint(fields=('makerspace', 'user'), name='uniq_booking_calendar_owner')]}),
    ]
