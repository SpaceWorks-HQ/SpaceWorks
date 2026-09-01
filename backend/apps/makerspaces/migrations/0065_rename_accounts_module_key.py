from django.db import migrations


OLD_KEY = "accounts"
NEW_KEY = "member_accounts"


def _rewrite_key(apps, source, target):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().only("id", "enabled_modules").iterator():
        modules = list(makerspace.enabled_modules or [])
        rewritten = [target if key == source else key for key in modules]
        if rewritten == modules:
            continue
        makerspace.enabled_modules = rewritten
        makerspace.save(update_fields=["enabled_modules"])


def rename_accounts_key(apps, schema_editor):
    _rewrite_key(apps, OLD_KEY, NEW_KEY)


def restore_accounts_key(apps, schema_editor):
    _rewrite_key(apps, NEW_KEY, OLD_KEY)


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0064_makerspace_lifecycle_state")]

    operations = [migrations.RunPython(rename_accounts_key, restore_accounts_key)]
