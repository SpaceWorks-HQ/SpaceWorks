"""Clear verified-email identity proof from every walk-in person record.

Migration 0015 revoked credentials and durable login identities but did not clear
``email_verified_at``.  Other workflows treat that stamp as identity proof, even though
a walk-in email was typed by staff and was never safe to trust as an account identity.

Accepted cost: a walk-in who legitimately verified an address must verify it again after
conversion to a real account.  The security boundary is more important than preserving a
verification whose provenance cannot be distinguished from the historical hole.
"""

from django.db import migrations


def clear_walk_in_email_verification(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_walk_in=True).update(email_verified_at=None)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0015_backfill_is_walk_in")]

    operations = [
        migrations.RunPython(
            clear_walk_in_email_verification,
            reverse_code=migrations.RunPython.noop,
        )
    ]
