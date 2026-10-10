"""F3 notification families and email streams; choices only, no backfill."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0027_device_notifications")]
    operations = [
        migrations.AlterField(
            model_name='chattemplate', name='feature',
            field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('api_access', 'API access'), ('devices', 'Devices'), ('payments', 'Payments'), ('stock', 'Stock and procurement'), ('certifications', 'Certifications')], max_length=32),
        ),
        migrations.AlterField(
            model_name='emailtemplate', name='stream',
            field=models.CharField(choices=[('hardware', 'Hardware'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('membership', 'Membership'), ('devices', 'Devices'), ('payments', 'Payments'), ('stock', 'Stock and procurement'), ('certifications', 'Certifications')], max_length=16),
        ),
        migrations.AlterField(
            model_name='notificationdeliverylog', name='feature',
            field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('api_access', 'API access'), ('devices', 'Devices'), ('payments', 'Payments'), ('stock', 'Stock and procurement'), ('certifications', 'Certifications')], max_length=32),
        ),
        migrations.AlterField(
            model_name='notificationpreference', name='feature',
            field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('api_access', 'API access'), ('devices', 'Devices'), ('payments', 'Payments'), ('stock', 'Stock and procurement'), ('certifications', 'Certifications')], max_length=32),
        ),
        migrations.AlterField(
            model_name='notificationrecipient', name='feature',
            field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('api_access', 'API access'), ('devices', 'Devices'), ('payments', 'Payments'), ('stock', 'Stock and procurement'), ('certifications', 'Certifications')], max_length=32),
        ),
    ]
