"""Record which accounts came from anonymous self-registration.

The generated ``member_<uuid>`` namespace has been exclusive to self-registration
since that flow shipped, so it is the durable upgrade signal for existing rows.
"""

from django.db import migrations, models
from django.db.models import F


def mark_existing_self_registrations(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        username__regex=r"^member_[0-9a-f]{32}$",
        self_registered_at__isnull=True,
    ).update(self_registered_at=F("date_joined"))


def unmark_existing_self_registrations(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(username__regex=r"^member_[0-9a-f]{32}$").update(
        self_registered_at=None
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0021_passwordresetenvelope")]

    operations = [
        migrations.AddField(
            model_name="user",
            name="self_registered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            mark_existing_self_registrations,
            unmark_existing_self_registrations,
        ),
    ]
