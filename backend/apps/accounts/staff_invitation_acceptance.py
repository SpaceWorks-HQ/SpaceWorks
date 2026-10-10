"""Email possession alone cannot take over an existing account or change its password."""

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, transaction
from django.db.models import F, Q
import secrets
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.accounts import audit_events
from apps.accounts.mfa_challenges import digest
from apps.accounts.models import User
from apps.accounts.models_mfa import UserMFA
from apps.accounts.models_staff_invitations import StaffInvitation
from apps.accounts.principal_guards import is_anonymous_requester
from apps.accounts.services_mfa import consume_code
from apps.accounts.services_staff_invitations import authority
from apps.audit.services import record
from apps.makerspaces import limits
from apps.makerspaces.models import Makerspace, MakerspaceMembership, MakerspaceRole
from apps.makerspaces.role_services import can_assign_role
from apps.makerspaces.servability import is_servable
from apps.tenant_migration.gate_runtime import tenant_write

GENERIC_ERROR = "Unable to accept this invitation. Check the link and credentials or contact the inviter."


def accept(request, *, token, makerspace_slug, password, code=""):
    candidate = StaffInvitation.objects.filter(token_digest=digest(token), makerspace__slug=makerspace_slug).first()
    if candidate is None:
        # Match a real password check's cost on the unknown-token path.
        make_password(password)
        raise ValidationError({"detail": GENERIC_ERROR})
    ok = False
    password_checked = False
    with tenant_write(candidate.makerspace_id):
        try:
            with transaction.atomic():
                space = Makerspace.objects.select_for_update().get(pk=candidate.makerspace_id)
                row = StaffInvitation.objects.select_for_update().get(pk=candidate.pk)
                if (row.accepted_at or row.revoked_at or row.expires_at <= timezone.now()
                        or row.failed_attempts >= 5 or not is_servable(space)):
                    raise ValidationError(GENERIC_ERROR)
                role = MakerspaceRole.objects.select_for_update().get(pk=row.role_id, makerspace=space)
                email = row.email
                # Accounts are platform-global: lock inviter and recipient in PK order,
                # even when the two invitations belong to different makerspaces.
                users = list(User.objects.select_for_update().filter(
                    Q(pk=row.created_by_id) | Q(email__iexact=email)).order_by("pk"))
                creator = next((user for user in users if user.pk == row.created_by_id), None)
                if creator is None:
                    raise ValidationError(GENERIC_ERROR)
                authority(creator, space, role)
                if sorted(role.granted_actions) != row.granted_actions:
                    raise ValidationError(GENERIC_ERROR)
                matches = [user for user in users if user.email.lower() == email.lower()]
                if len(matches) > 1:
                    raise ValidationError(GENERIC_ERROR)
                user = matches[0] if matches else None
                if user:
                    if (not user.is_active or user.is_tenant_dump_stub or user.is_walk_in
                            or user.must_change_password or is_anonymous_requester(user)
                            or user.access_status != User.AccessStatus.ACTIVE):
                        raise ValidationError(GENERIC_ERROR)
                    password_checked = True
                    authenticated = authenticate(request=request, username=user.username, password=password)
                    if authenticated is None:
                        raise ValidationError(GENERIC_ERROR)
                    mfa = UserMFA.objects.select_for_update().filter(user=user, enabled_at__isnull=False).first()
                    if mfa and not consume_code(mfa, code):
                        raise ValidationError(GENERIC_ERROR)
                else:
                    # The invite proves email ownership, but cannot be used as a password reset.
                    user = User(email=row.email, username="staff_" + secrets.token_hex(12))
                    # Hash before validation so weak new-account passwords are not a
                    # cheaper probe than wrong existing-account passwords.
                    user.set_password(password)
                    password_checked = True
                    validate_password(password, user)
                    user.email_verified_at = timezone.now()
                    user.save()
                membership = MakerspaceMembership.objects.select_for_update().filter(
                    user=user, makerspace=space).first()
                if membership and membership.status != "active":
                    raise ValidationError(GENERIC_ERROR)
                can_assign_role(creator, space, role, target_membership=membership)
                if membership is None:
                    limits.check_quota(space, "staff", adding=1)
                    membership = MakerspaceMembership(user=user, makerspace=space)
                membership.assigned_role = role
                membership.role = role.legacy_role or MakerspaceMembership.Role.CUSTOM
                membership.save()
                row.accepted_at, row.accepted_by = timezone.now(), user
                row.save(update_fields=["accepted_at", "accepted_by"])
                record(user, "staff.invitation_accepted", makerspace=space, target=row,
                       meta={"membership_id": membership.pk, "role_id": role.pk})
                ok = True
        except (APIException, DjangoValidationError, IntegrityError, ObjectDoesNotExist):
            if not password_checked:
                make_password(password)
            # The inner transaction rolls back grants, but a wrong credential commits its refusal.
            with transaction.atomic():
                StaffInvitation.objects.filter(pk=candidate.pk, accepted_at__isnull=True,
                                               failed_attempts__lt=5).update(
                    failed_attempts=F("failed_attempts") + 1)
                audit_events.record_auth_event(None, "staff.invitation_accept_failed",
                                               meta={"invitation_hash": audit_events.fingerprint(candidate.pk)})
    if not ok:
        raise ValidationError({"detail": GENERIC_ERROR})
    # Exactly the same success body for a newly created or linked account, no tokens/PII.
    return {"detail": "Invitation accepted. Sign in with your email and password."}
