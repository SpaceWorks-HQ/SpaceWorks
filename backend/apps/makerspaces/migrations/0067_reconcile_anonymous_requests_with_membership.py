"""Close the membership + account-less-requests pair on rows that already carry both.

`Makerspace.save()` now makes the combination unreachable, but that only guards writes
from here on. A row written before the rule — by the `/control/` capability matrix, a
module install, or a restored backup — can still be sitting in the impossible state, and
`RequestSubmitView` would have admitted a stranger past the membership requirement.

Fixed in SQL rather than through the model on purpose: this must not depend on `save()`
(the thing being backfilled for), and it must not fan out per-row on a large install.
"""

from django.db import migrations


def close_anonymous_requests_where_membership_installed(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    # `enabled_modules` is a JSONField holding a list of keys, so containment is the
    # right test — `contains` compiles to the jsonb @> operator.
    Makerspace.objects.filter(
        anonymous_requests_enabled=True,
        enabled_modules__contains=["membership"],
    ).update(anonymous_requests_enabled=False)


def noop_reverse(apps, schema_editor):
    """Deliberately not reversed.

    Re-opening account-less requests on a makerspace that has `membership` installed is
    the security hole this migration exists to close; a downgrade must not reinstate it.
    Reversing the code change is enough to restore the old behaviour for anyone who
    re-enables the flag on purpose.
    """


class Migration(migrations.Migration):
    dependencies = [("makerspaces", "0066_makerspace_anonymous_requester_and_more")]

    operations = [
        migrations.RunPython(
            close_anonymous_requests_where_membership_installed,
            noop_reverse,
        ),
    ]
