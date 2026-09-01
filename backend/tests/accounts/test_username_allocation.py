import re

import pytest
from django.db import transaction

from apps.accounts.models import User
from apps.accounts.username_allocation import (
    MAX_ATTEMPTS,
    UsernameAllocationError,
    allocate_username,
)

MIGRATION_USERNAME_RE = r"^walkin_[[:alnum:]_]+_[a-z0-9]{6}$"
PYTHON_EQUIVALENT_RE = re.compile(r"^walkin_[\w]+_[a-z0-9]{6}$", re.UNICODE)


def _create_user(username, *, email=""):
    return User.objects.create_user(username=username, email=email)


@pytest.mark.django_db(transaction=True)
def test_sequence_collision_retries_inside_savepoint_and_preserves_outer_work(monkeypatch):
    User.objects.create_user(username="walkin_josé_núñez_taken1")
    tails = iter(("taken1", "free22"))
    monkeypatch.setattr(
        "apps.accounts.username_allocation.get_random_string",
        lambda length, alphabet: next(tails),
    )

    with transaction.atomic():
        before = User.objects.create_user(username="batch_work_before_allocation")
        allocated = allocate_username(
            "José Núñez", create=lambda username: _create_user(username, email="new@example.test")
        )
        after = User.objects.create_user(username="batch_work_after_allocation")

    assert allocated.username == "walkin_josé_núñez_free22"
    assert PYTHON_EQUIVALENT_RE.fullmatch(allocated.username)
    assert User.objects.filter(email="new@example.test").count() == 1
    assert User.objects.filter(pk__in=(before.pk, after.pk)).count() == 2


@pytest.mark.django_db(transaction=True)
def test_constant_collision_raises_typed_bounded_error(monkeypatch):
    User.objects.create_user(username="walkin_member_taken1")
    calls = 0

    def constant(length, alphabet):
        nonlocal calls
        calls += 1
        return "taken1"

    monkeypatch.setattr("apps.accounts.username_allocation.get_random_string", constant)

    with pytest.raises(UsernameAllocationError):
        allocate_username("", create=_create_user)

    assert calls == MAX_ATTEMPTS
    assert User.objects.filter(username="walkin_member_taken1").count() == 1


@pytest.mark.django_db
def test_first_attempt_matches_migration_classifier(monkeypatch):
    monkeypatch.setattr(
        "apps.accounts.username_allocation.get_random_string",
        lambda length, alphabet: "abc123",
    )
    allocated = allocate_username("A Name", create=_create_user)

    assert MIGRATION_USERNAME_RE == r"^walkin_[[:alnum:]_]+_[a-z0-9]{6}$"
    assert PYTHON_EQUIVALENT_RE.fullmatch(allocated.username)
