"""Mark walk-in records created before `is_walk_in` existed, and revoke any credential
they already acquired through the hole the flag closes, including durable identities.

The flag defaults to False, so every walk-in created by phase 9 before this migration
would stay resettable by forgot-password -- which is the whole hole the flag closes. A
default change never rewrites stored rows, so the backfill has to be explicit, the same
reasoning as `makerspaces/0050`.

`member.walk_in_created` is the authoritative record, but it is makerspace-scoped and
is deleted when its makerspace is purged while the global User survives. The durable
fallback is the `walkin_` username prefix generated for every walk-in. Self-registration
uses the separate `member_<uuid>` namespace, so the two cannot collide. If a manually
created username ever does collide, a superadmin can untick `is_walk_in`.

Matching on "unusable password" was rejected -- that is also true of an invited
account that has not set one yet, and marking one of those would lock a real person out
of their own recovery.
"""

from django.contrib.auth.hashers import make_password
from django.db import migrations
from django.utils import timezone


def mark_walk_ins(apps, schema_editor):
    AuditLog = apps.get_model("audit", "AuditLog")
    Membership = apps.get_model("makerspaces", "MakerspaceMembership")
    User = apps.get_model("accounts", "User")

    membership_ids = [
        int(target_id)
        for target_id in AuditLog.objects.filter(
            action="member.walk_in_created"
        ).values_list("target_id", flat=True)
        if target_id and target_id.isdigit()
    ]
    audit_user_ids = Membership.objects.filter(pk__in=membership_ids).values_list(
        "user_id", flat=True
    )
    # Like the unusable-password test rejected above, a prefix alone is too blunt a
    # heuristic for destructive credential revocation. The generated username shape,
    # including its exact six-character random tail, is far more specific.
    #
    # The stem class must be `[[:alnum:]]`, NOT `[a-z0-9]`. `_available_username` builds
    # the stem with `char.isalnum()`, which is true for every Unicode letter, so an
    # ASCII-only class silently skipped a large share of real names -- verified against
    # Postgres: `José Núñez` becomes `walkin_josé_núñez_w96uow` and did not match, and
    # neither did Cyrillic, CJK or Arabic. Accented Latin names are the common case here,
    # not an exotic one. A skipped row keeps a working password, and if its makerspace was
    # already purged the audit-derived signal above is gone too, so this regex is the only
    # thing left that can identify it. (Devanagari lands here via a different route: its
    # combining marks are category Mn, not alnum, so they become underscores.)
    prefix_user_ids = User.objects.filter(
        username__regex=r"^walkin_[[:alnum:]_]+_[a-z0-9]{6}$"
    ).values_list("pk", flat=True)
    user_ids = list(set(audit_user_ids).union(prefix_user_ids))
    if not user_ids:
        return
    User.objects.filter(pk__in=user_ids).update(is_walk_in=True)

    # Marking the row is not enough on an upgrading database. The whole point of the
    # flag is that a walk-in was reachable by forgot-password BEFORE it existed, so any
    # walk-in that already went through that flow holds a WORKING password, and none of
    # the login or refresh paths consult `is_walk_in` -- the flag is enforced wherever a
    # credential can be CREATED, which is the right place going forward and does nothing
    # about state that already exists. A marker alone would therefore leave exactly the
    # accounts this migration exists for still able to sign in.
    #
    # `make_password(None)` is how `set_unusable_password` writes its sentinel; it is
    # spelled out because historical models carry no methods.
    compromised = User.objects.filter(pk__in=user_ids).exclude(
        password__startswith="!"
    )
    compromised.update(password=make_password(None))

    # Their refresh tokens outlive the password, so a live session would keep rotating.
    # Best-effort: `token_blacklist` is a `simplejwt` app and may not be installed.
    try:
        OutstandingToken = apps.get_model("token_blacklist", "OutstandingToken")
        BlacklistedToken = apps.get_model("token_blacklist", "BlacklistedToken")
    except LookupError:
        pass
    else:
        outstanding = OutstandingToken.objects.filter(user_id__in=user_ids)
        already = set(
            BlacklistedToken.objects.filter(token_id__in=outstanding).values_list(
                "token_id", flat=True
            )
        )
        BlacklistedToken.objects.bulk_create(
            [
                BlacklistedToken(token_id=token_id)
                for token_id in outstanding.values_list("pk", flat=True)
                if token_id not in already
            ],
            ignore_conflicts=True,
        )

    # The password was only the credential they STARTED with. A walk-in who went
    # through the old hole had a working session, and could have used it to link
    # something durable that outlives a password reset. Each of these has a login path
    # that never reaches the `is_walk_in` guard:
    #
    #   - `SocialIdentity`: `resolve_social_identity` returns as soon as an existing
    #     identity matches the provider subject, BEFORE the auto-link guard -- so a
    #     linked Google account signs them straight in.
    #   - `phone_e164` + `phone_verified_at`: a verified number is a login identity in
    #     its own right, resolved by number, and phone login does not read the marker.
    #   - `DeviceGrant`: a native grant mints its own rotating refresh family, so
    #     blacklisting today's tokens above does not stop tomorrow's.
    #
    # Revoked rather than left for a login-time check, because this is historical state
    # on one upgrade -- a permanent guard on every login path would be paying forever
    # for a window that has closed.
    SocialIdentity = apps.get_model("accounts", "SocialIdentity")
    SocialIdentity.objects.filter(user_id__in=user_ids).delete()

    # `User` is the model being migrated, so it is always resolvable -- no guard needed.
    User.objects.filter(pk__in=user_ids).update(phone_e164="", phone_verified_at=None)

    DeviceGrant = apps.get_model("accounts", "DeviceGrant")
    DeviceGrant.objects.filter(user_id__in=user_ids).update(
        status="revoked", revoked_at=timezone.now()
    )


def unmark(apps, schema_editor):
    # Reversible in the direction that matters -- the marker. The revoked credentials
    # are deliberately NOT restored: they were usable only because of the hole this
    # migration closes, and a reverse that handed them back would reopen it. Anyone
    # affected was never supposed to have a login, and the recovery is to be invited as
    # a real member.
    apps.get_model("accounts", "User").objects.filter(is_walk_in=True).update(
        is_walk_in=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_user_is_walk_in"),
        ("audit", "0001_initial"),
        ("makerspaces", "0002_makerspacemembership"),
        ("token_blacklist", "0001_initial"),
    ]

    operations = [migrations.RunPython(mark_walk_ins, unmark)]
