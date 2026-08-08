"""The tombstone profile: a separate pytest run with apps actually removed.

Kept out of the default suite on purpose (plan B4). URL routing, admin registration
and the Unfold sidebar are all decided at import time, so the only honest way to test
a tombstoned deployment is to *be* one — a second process with `TOMBSTONED_APPS` set
before Django is configured. That cannot coexist with the all-active suite, which
asserts the opposite for the same objects (`test_admin_registration` requires
`ToBuyItem` to be registered; here it must not be).

Run it with the apps under test named in the environment:

    TOMBSTONED_APPS=bookings,events,maintenance,notifications,presence,procurement,warranty pytest tests/tombstone

Two failure modes are handled differently on purpose:

* A **whole-tree run** (`pytest tests/`) sweeps this directory up with no profile set.
  Erroring there would mean the ordinary suite could not be run at all, so the
  directory is skipped instead.
* An **explicit run** (`pytest tests/tombstone`) with no profile set is a mistake worth
  stopping for. Collecting nothing would report green while proving nothing, which is
  worse than not running it.
"""

import pytest

from apps.separability.tombstones import tombstoned_app_labels

# The apps these tests expect to be tombstoned. Grows by one per phase of plan B6.
TOMBSTONE_PROFILE_APPS = frozenset({
    "procurement", "notifications", "warranty", "maintenance", "presence", "events", "bookings",
    "payments", "updates",
})

_PROFILE_ACTIVE = tombstoned_app_labels() == TOMBSTONE_PROFILE_APPS

# Read at directory-collection time, after pytest_configure below has had its say.
collect_ignore_glob = [] if _PROFILE_ACTIVE else ["test_*.py"]


def pytest_configure(config):
    if _PROFILE_ACTIVE:
        return
    targeted = any("tombstone" in str(arg) for arg in config.args)
    if not targeted:
        return
    raise pytest.UsageError(
        "tests/tombstone must run under the tombstone profile. Expected "
        f"TOMBSTONED_APPS={','.join(sorted(TOMBSTONE_PROFILE_APPS))}, got "
        f"{','.join(sorted(tombstoned_app_labels())) or '(unset)'}. Set the variable "
        "in the environment before pytest starts -- it is read while Django settings "
        "are imported, so an override_settings is too late."
    )
