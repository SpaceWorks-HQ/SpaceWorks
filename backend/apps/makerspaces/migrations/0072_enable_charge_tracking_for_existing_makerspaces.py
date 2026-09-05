"""Turn charge tracking ON for makerspaces that already exist.

The `charges.*` family decides whether money owed is RECORDED at all, independently of
the `payments` module, which now governs only the online rail. `enabled_features` is
stored per row, so a new `default_enabled=True` reaches new makerspaces only -- without
this backfill every existing space would read the keys as OFF and silently stop
recording booking, event, machine, membership and loan charges the day this ships.

Each domain key inherits the state of the `payments.<domain>` feature it replaces, so a
space keeps charging for exactly what it charged for yesterday and nothing more. New
makerspaces get all six on by default instead, since they have no prior intent to carry.

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


#: Each tracking key and the online-payment feature whose state it inherits. A space
#: that deliberately kept `payments.bookings` OFF was not charging for bookings, and
#: switching tracking on for it would start creating debts it never had -- with
#: `charges.loans` it could even start BLOCKING issue. So intent is carried across per
#: domain rather than assumed.
DOMAIN_SOURCE = {
    "charges.bookings": "payments.bookings",
    "charges.events": "payments.events",
    "charges.machines": "payments.machines",
    "charges.membership": "payments.membership",
    "charges.loans": "payments.loans",
}


def enable_tracking(apps, schema_editor):
    Makerspace = apps.get_model("makerspaces", "Makerspace")
    for makerspace in Makerspace.objects.all().iterator():
        features = set(makerspace.enabled_features or [])
        # The master switch goes on for everyone: on its own it enables nothing, because
        # each domain key still has to be present below.
        wanted = {"charges.enabled"} | {
            key for key, source in DOMAIN_SOURCE.items() if source in features
        }
        if features.issuperset(wanted):
            continue
        makerspace.enabled_features = sorted(features | wanted)
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
