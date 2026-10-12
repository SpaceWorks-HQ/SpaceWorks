import datetime
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('integrations', '0029_personal_delivery_controls'), ('makerspaces', '0085_space_pack_profile')]
    operations = [migrations.CreateModel(name='NotificationTimingPolicy', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('quiet_start', models.TimeField(default=datetime.time(22))),
        ('quiet_end', models.TimeField(default=datetime.time(8))),
        ('channels', models.JSONField(default=list)),
        ('digest_at', models.TimeField(default=datetime.time(8))),
        ('bounce_secret', models.TextField(blank=True)),
        ('makerspace', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='makerspaces.makerspace')),
    ])]
