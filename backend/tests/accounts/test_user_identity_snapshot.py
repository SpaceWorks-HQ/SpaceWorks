"""`User.from_db` must not force-load deferred identity columns.

`from_db` snapshots `email` and `phone_e164` so `save()` can tell whether either
changed and drop the matching verified stamp. Reading them by attribute access made
that snapshot fatal on any deferred query: `refresh_from_db` issues its own
`.only(<field>)` query, whose `from_db` then defers the OTHER column, and the two
snapshots load each other until Python's recursion limit. `/analytics/top-borrowers`
selects `.only(...)` over `select_related("requester")`, so the endpoint 500'd.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def make_user(username="deferred-user", **kwargs):
    return get_user_model().objects.create_user(
        username=username,
        email=kwargs.pop("email", f"{username}@example.test"),
        access_status=User.AccessStatus.ACTIVE,
        **kwargs,
    )


@pytest.mark.parametrize(
    "only_fields",
    [
        ("id", "username"),          # both identity columns deferred
        ("id", "email"),             # phone_e164 deferred
        ("id", "phone_e164"),        # email deferred
    ],
)
def test_only_queries_omitting_identity_columns_do_not_recurse(only_fields):
    make_user()
    loaded = get_user_model().objects.only(*only_fields).first()
    assert loaded is not None
    # Touching the deferred column must resolve in one load, not re-enter from_db.
    assert loaded.email is not None
    assert loaded.phone_e164 is not None


def test_deferred_load_does_not_snapshot_what_it_did_not_read():
    make_user()
    loaded = get_user_model().objects.only("id", "username").first()
    assert getattr(loaded, "_loaded_email", None) is None
    assert getattr(loaded, "_loaded_phone_e164", None) is None


def test_editing_email_on_a_deferred_instance_still_clears_the_verified_stamp():
    """The snapshot is a security control, so a missing snapshot must not read as
    "unchanged" -- that would keep a verified stamp on an address nobody proved."""
    user = make_user(email="original@example.test")
    get_user_model().objects.filter(pk=user.pk).update(email_verified_at=timezone.now())

    loaded = get_user_model().objects.only("id", "username").first()
    loaded.email = "moved@example.test"
    loaded.save()

    loaded.refresh_from_db()
    assert loaded.email == "moved@example.test"
    assert loaded.email_verified_at is None


def test_editing_phone_on_a_deferred_instance_still_clears_the_verified_stamp():
    user = make_user()
    get_user_model().objects.filter(pk=user.pk).update(
        phone_e164="+15550101010", phone_verified_at=timezone.now()
    )

    loaded = get_user_model().objects.only("id", "username").first()
    loaded.phone_e164 = "+15550202020"
    loaded.save()

    loaded.refresh_from_db()
    assert loaded.phone_e164 == "+15550202020"
    assert loaded.phone_verified_at is None


def test_an_unchanged_deferred_save_keeps_both_stamps():
    """The baseline lookup must not manufacture a change and revoke a real verification."""
    user = make_user(email="steady@example.test")
    stamp = timezone.now()
    get_user_model().objects.filter(pk=user.pk).update(
        phone_e164="+15550303030", email_verified_at=stamp, phone_verified_at=stamp
    )

    loaded = get_user_model().objects.only("id", "username").first()
    loaded.first_name = "Renamed"
    loaded.save()

    loaded.refresh_from_db()
    assert loaded.email_verified_at is not None
    assert loaded.phone_verified_at is not None
