from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bookings", "0007_bookablespace_payment_amount")]

    operations = [
        migrations.AlterField(
            model_name="bookablespace",
            name="approval_mode",
            field=models.CharField(
                choices=[
                    ("instant", "Instant confirmation"),
                    ("approve", "Staff approval required"),
                ],
                default="approve",
                max_length=16,
            ),
        ),
    ]
