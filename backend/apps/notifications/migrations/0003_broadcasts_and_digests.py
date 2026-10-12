from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('notifications', '0002_personal_inbox'), ('makerspaces', '0085_space_pack_profile'),
                    migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='membernotificationpreference', name='daily_digest', field=models.BooleanField(default=False)),
        migrations.CreateModel(name='MemberBroadcast', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('title', models.TextField()), ('body', models.TextField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('makerspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='makerspaces.makerspace')),
            ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
        ], options={'ordering': ['-created_at', '-pk']}),
    ]
