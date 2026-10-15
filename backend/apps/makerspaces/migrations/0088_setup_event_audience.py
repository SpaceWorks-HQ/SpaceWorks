from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0087_remove_in_app_updates")]
    operations = [migrations.AddField(
        model_name="makerspace", name="event_default_registration_audience",
        field=models.CharField(max_length=8, default="members", choices=[
            ("members", "Members"), ("accounts", "Authenticated accounts"), ("invite", "Invited accounts")]),
    )]
