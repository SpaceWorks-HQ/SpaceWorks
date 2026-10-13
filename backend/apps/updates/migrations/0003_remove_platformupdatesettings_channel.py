from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("updates", "0002_update_recovery")]

    operations = [
        migrations.RemoveField(model_name="platformupdatesettings", name="channel"),
    ]
