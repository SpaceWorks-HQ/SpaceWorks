from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("makerspaces", "0063_makerspacemembership_activated_actor_snapshot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="makerspace",
            name="lifecycle_state",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("importing", "Importing"),
                    ("aborted", "Aborted"),
                ],
                db_index=True,
                default="active",
                max_length=16,
            ),
        ),
    ]
