"""Device notification feature and staff email stream (choice-only state changes)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integrations", "0025_webhook_channel")]
    operations = [
        migrations.AlterField(model_name='notificationpreference', name="feature",
                              field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('devices', 'Devices')], max_length=32)),
        migrations.AlterField(model_name='notificationdeliverylog', name="feature",
                              field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('devices', 'Devices')], max_length=32)),
        migrations.AlterField(model_name='notificationrecipient', name="feature",
                              field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('devices', 'Devices')], max_length=32)),
        migrations.AlterField(model_name='chattemplate', name="feature",
                              field=models.CharField(choices=[('hardware_requests', 'Hardware requests'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('members', 'Members'), ('devices', 'Devices')], max_length=32)),
        migrations.AlterField(model_name="emailtemplate", name="stream",
                              field=models.CharField(choices=[('hardware', 'Hardware'), ('printing', 'Printing'), ('events', 'Events'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance'), ('membership', 'Membership'), ('devices', 'Devices')], max_length=16)),
    ]
