from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payments", "0018_offline_refund_receipt")]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="subject_type",
            field=models.CharField(max_length=48, choices=[
                ("machine_service_request", "Machine service request"),
                ("booking", "Booking"),
                ("event_registration", "Event registration"),
                ("makerspace_membership", "Makerspace membership"),
                ("membership_term", "Membership renewal"),
                ("membership_request", "Membership admission"),
                ("loan_deposit", "Loan deposit"),
                ("loan_late_fee", "Loan late fee"),
            ]),
        ),
    ]
