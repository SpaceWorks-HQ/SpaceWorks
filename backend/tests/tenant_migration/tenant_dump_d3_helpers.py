from django.utils import timezone

from apps.accounts.models import User
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.recipients import fingerprint_for
from apps.backup.recipients_bech32 import convert_bits, encode
from apps.makerspaces.models import Makerspace, MakerspaceMembership


def makerspace(slug, *, superadmin_access=True, modules=("notifications",)):
    return Makerspace.objects.create(
        name=slug,
        slug=slug,
        superadmin_access_enabled=superadmin_access,
        enabled_modules=list(modules),
    )


def manager(space, suffix="manager", *, mailable=True, opted_in=True):
    user = User.objects.create_user(
        username=f"{space.slug}-{suffix}",
        email=f"{space.slug}-{suffix}@example.com" if mailable else "",
        access_status=User.AccessStatus.ACTIVE,
    )
    MakerspaceMembership.objects.create(
        makerspace=space,
        user=user,
        role=MakerspaceMembership.Role.SPACE_MANAGER,
        receives_notifications=opted_in,
    )
    return user


def operator(suffix="operator"):
    return User.objects.create_user(
        username=suffix,
        email=f"{suffix}@example.com",
        role=User.Role.SUPERADMIN,
        is_superuser=True,
        access_status=User.AccessStatus.ACTIVE,
    )


def recipient(space, seed):
    public_recipient = encode(
        "age",
        convert_bits(bytes([seed]) * 32, 8, 5, pad=True),
    )
    return MakerspaceArchiveRecipient.objects.create(
        makerspace=space,
        public_recipient=public_recipient,
        fingerprint=fingerprint_for(public_recipient),
        label=f"Custodian {seed}",
        verified_at=timezone.now(),
    )
