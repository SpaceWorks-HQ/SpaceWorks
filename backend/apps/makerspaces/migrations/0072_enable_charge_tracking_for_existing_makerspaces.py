"""Turn charge tracking ON for makerspaces that already exist.

The `charges.*` family decides whether money owed is RECORDED at all, independently of
the `payments` module, which now governs only the online rail. `enabled_features` is
stored per row, so a new `default_enabled=True` reaches new makerspaces only -- without
this backfill every existing space would read the keys as OFF and silently stop
recording booking, event, machine, membership and loan charges the day this ships.

Defaulting these ON cannot invent charges out of nowhere: the real trigger is still a
configured amount (a booking price, event fee, machine pricing row, dues, or a deposit
rule). A space that has priced nothing gets no rows either way.

Same shape as `0050` and `0051`: a one-time backfill with a working reverse, touching
only rows that lack the keys.
"""

from django.db import migrations

FEATURE_KEYS = (
    "charges.enabled",
    "charges.bookings",
    "charges.events",
    "charges.machines",
    "charges.membership",
    "charges.loans",
)


def enable_tracking(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        features = set(makerspace.enabled_features or [])
        if features.issuperset(FEATURE_KEYS):
            continue
        makerspace.enabled_features = sorted(features | set(FEATURE_KEYS))
        makerspace.save(update_fields=["enabled_features"])


def disable_tracking(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        features = set(makerspace.enabled_features or [])
        if features.isdisjoint(FEATURE_KEYS):
            continue
        makerspace.enabled_features = sorted(features - set(FEATURE_KEYS))
        makerspace.save(update_fields=["enabled_features"])


class Migration(migrations.Migration):
    # Chained off the ACTUAL leaf, read from the migrations directory.
    dependencies = [
        ("makerspaces", "0071_membership_plans_terms_invitation_requests")
    ]

    operations = [migrations.RunPython(enable_tracking, disable_tracking)]
