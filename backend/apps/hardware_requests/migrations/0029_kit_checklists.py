from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("hardware_requests", "0028_loan_renewal_count")]
    operations = [
        migrations.AddField(model_name="hardwarerequest", name="box_issue_checklist",
                            field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name="hardwarerequestitem", name="issue_checklist",
                            field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name="returnevent", name="kit_checklist",
                            field=models.JSONField(default=list, blank=True)),
        migrations.AlterField(model_name="requesteraccountability", name="request_item",
                              field=models.ForeignKey(to="hardware_requests.hardwarerequestitem",
                                                      null=True, blank=True,
                                                      on_delete=django.db.models.deletion.PROTECT)),
    ]
