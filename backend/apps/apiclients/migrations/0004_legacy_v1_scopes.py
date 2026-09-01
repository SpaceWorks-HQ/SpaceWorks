from django.db import migrations


LEGACY_SCOPES = ["legacy:v1"]


def add_legacy_v1_scope(apps, _schema_editor):
    ApiClient = apps.get_model("apiclients", "ApiClient")
    ApiClient.objects.filter(scopes=[]).update(scopes=LEGACY_SCOPES)


def remove_legacy_v1_scope(apps, _schema_editor):
    ApiClient = apps.get_model("apiclients", "ApiClient")
    ApiClient.objects.filter(scopes=LEGACY_SCOPES).update(scopes=[])


class Migration(migrations.Migration):
    dependencies = [("apiclients", "0003_apikeyrequest")]

    operations = [
        migrations.RunPython(add_legacy_v1_scope, remove_legacy_v1_scope),
    ]
