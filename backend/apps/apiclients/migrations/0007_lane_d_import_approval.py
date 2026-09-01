from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("apiclients", "0006_apiclient_last_seen_at_apiclient_last_seen_ip"),
        ("makerspaces", "0064_makerspace_lifecycle_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="apiclient",
            name="credential_delivered_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="apiclient",
            name="import_provenance_digest",
            field=models.CharField(
                blank=True, editable=False, max_length=64, null=True, unique=True
            ),
        ),
        migrations.CreateModel(
            name="ApiClientImportApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("artifact_sha256", models.CharField(max_length=64)),
                ("capture_id", models.UUIDField()),
                ("source_catalog_sha256", models.CharField(max_length=64)),
                ("source_client_ref", models.CharField(max_length=64)),
                ("source_entry_sha256", models.CharField(max_length=64)),
                ("approval_record_sha256", models.CharField(max_length=64, unique=True)),
                ("host_principal", models.CharField(max_length=255)),
                ("approval_nonce", models.CharField(max_length=64, unique=True)),
                ("approved_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("api_client", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="import_approval", to="apiclients.apiclient")),
                ("makerspace", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="api_client_import_approvals", to="makerspaces.makerspace")),
            ],
        ),
    ]
