"""Collision-safe local identity resolution for OIDC browser callbacks."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import audit_events
from apps.accounts.models import User
from apps.accounts.models_social import SocialIdentity, SocialSurface
from apps.accounts.services_social_identity import (
    SocialResolutionError,
    resolve_social_identity,
)
from apps.accounts.transition_services import (
    WalkInTransitionError,
    transition_walk_in_to_account,
)
from apps.audit import services as audit
from apps.makerspaces.models import MakerspaceMembership


def resolve_browser_identity(attempt, claims, *, allow_user_creation):
    if attempt.intended_user_id is None:
        return resolve_social_identity(
            provider=attempt.provider,
            claims=claims,
            surface=SocialSurface.MEMBER,
            allow_auto_link=claims.get("allow_auto_link", True),
            allow_user_creation=allow_user_creation,
        )
    return _transition_bound_walk_in(attempt, claims)


def _transition_bound_walk_in(attempt, claims):
    subject = claims["sub"]
    asserted_email = (claims.get("email") or "").strip().lower()
    verified = claims.get("email_verified") is True
    try:
        with transaction.atomic():
            target = User.objects.select_for_update().get(pk=attempt.intended_user_id)
            membership = (
                MakerspaceMembership.objects.select_for_update()
                .filter(
                    pk=attempt.intended_membership_id,
                    user=target,
                    status="active",
                )
                .first()
            )
            subject_identity = (
                SocialIdentity.objects.select_for_update()
                .filter(provider=attempt.provider, provider_sub=subject)
                .first()
            )
            email_users = list(
                User.objects.select_for_update()
                .filter(email__iexact=asserted_email)
                .exclude(email="")
            ) if asserted_email else []
            current_identity = (
                SocialIdentity.objects.select_for_update()
                .filter(user=target, provider=attempt.provider)
                .first()
            )
            if membership is None or not target.is_walk_in:
                raise SocialResolutionError("identity_conflict", 409)
            if not verified or not asserted_email or target.email.lower() != asserted_email:
                raise SocialResolutionError("identity_conflict", 409)
            if any(row.pk != target.pk for row in email_users):
                raise SocialResolutionError("identity_conflict", 409)
            if subject_identity is not None and subject_identity.user_id != target.pk:
                raise SocialResolutionError("identity_conflict", 409)
            if current_identity is not None and current_identity.provider_sub != subject:
                raise SocialResolutionError("provider_already_linked", 409)
            if claims.get("allow_auto_link") is not True:
                raise SocialResolutionError("account_link_required", 409)

            def link_identity(locked):
                if current_identity is None:
                    SocialIdentity.objects.create(
                        user=locked,
                        provider=attempt.provider,
                        provider_sub=subject,
                    )
                locked.email_verified_at = timezone.now()
                locked.save(update_fields=["email_verified_at"])
                audit.record(
                    None,
                    "auth.social_identity_linked",
                    target=locked,
                    meta={
                        "provider": attempt.provider,
                        "subject_hash": audit_events.fingerprint(subject),
                    },
                )

            user = transition_walk_in_to_account(
                target,
                actor=None,
                credential_writer=link_identity,
            )
            return user, "transitioned"
    except WalkInTransitionError as exc:
        raise SocialResolutionError("identity_conflict", 409) from exc
    except IntegrityError as exc:
        # The transition, identity link, revocations and audits share this transaction.
        # A concurrent uniqueness winner therefore rolls everything back before the
        # caller can mint a session.
        raise SocialResolutionError("identity_conflict", 409) from exc
