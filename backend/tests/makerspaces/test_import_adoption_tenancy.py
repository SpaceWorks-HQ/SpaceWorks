import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.makerspaces.import_adoption import adopt_pending_membership
from apps.makerspaces.models import (
    Makerspace,
    MakerspaceMembership,
    MakerspaceRole,
    MakerspaceWaiver,
    PendingImportedMembership,
)

pytestmark = pytest.mark.django_db


def user(name):
    return User.objects.create_user(
        username=name,
        email=f"{name}@example.test",
        email_verified_at=timezone.now(),
    )


def pending(makerspace, target, source_id, **values):
    fields = {
        "makerspace": makerspace,
        "email": target.email,
        "created_at": timezone.now(),
        "source_membership_id": source_id,
    }
    fields.update(values)
    return PendingImportedMembership.objects.create(**fields)


def test_pending_identity_is_unique_by_casefolded_email_and_source_row():
    makerspace = Makerspace.objects.create(name="Unique", slug="pending-unique")
    target = user("pending-unique-target")
    pending(makerspace, target, "source-1")

    with pytest.raises(IntegrityError), transaction.atomic():
        pending(makerspace, target, "source-2", email=target.email.upper())
    with pytest.raises(IntegrityError), transaction.atomic():
        pending(
            makerspace,
            user("pending-other-target"),
            "source-1",
        )


def test_adoption_rejects_a_cross_tenant_waiver_in_code():
    own = Makerspace.objects.create(name="Own", slug="adoption-own")
    other = Makerspace.objects.create(name="Other", slug="adoption-other")
    target = user("cross-waiver-target")
    waiver = MakerspaceWaiver.objects.create(
        makerspace=other,
        version="foreign",
        body="Foreign terms",
    )
    imported = pending(
        own,
        target,
        "cross-waiver-source",
        accepted_waiver=waiver,
        waiver_version_accepted=waiver.version,
        waiver_accepted_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="another makerspace"):
        adopt_pending_membership(target, imported)

    assert not MakerspaceMembership.objects.filter(makerspace=own, user=target).exists()


def test_adoption_rejects_when_only_member_role_belongs_to_another_tenant():
    own = Makerspace.objects.create(name="Own role", slug="adoption-own-role")
    other = Makerspace.objects.create(name="Other role", slug="adoption-other-role")
    target = user("cross-role-target")
    other_member = MakerspaceRole.objects.get(makerspace=other, slug="member")
    other_member.delete()
    own_member = MakerspaceRole.objects.get(makerspace=own, slug="member")
    MakerspaceRole.objects.filter(pk=own_member.pk).update(makerspace=other)
    imported = pending(own, target, "cross-role-source")

    with pytest.raises(ValidationError, match="valid Member role"):
        adopt_pending_membership(target, imported)

    assert not MakerspaceMembership.objects.filter(makerspace=own, user=target).exists()
