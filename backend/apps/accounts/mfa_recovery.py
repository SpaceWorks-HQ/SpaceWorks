"""Host-only recovery; does not waive the superadmin enrollment floor."""

import uuid

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import audit_events
from apps.accounts.models import User
from apps.accounts.models_mfa import UserMFA, MFAChallenge
from apps.accounts.services_tokens import blacklist_outstanding_tokens


@transaction.atomic
def reset_superadmin_mfa(user):
    user = User.objects.select_for_update().get(pk=user.pk)
    if not (user.is_superuser or user.role == User.Role.SUPERADMIN):
        raise PermissionDenied("Only an existing superadmin may use host MFA recovery.")
    row, _ = UserMFA.objects.get_or_create(user=user)
    row.secret, row.enabled_at, row.last_step = "", None, -1
    row.recovery_digests, row.version = [], uuid.uuid4()
    row.save()
    MFAChallenge.objects.filter(user=user).delete()
    blacklist_outstanding_tokens(user)
    audit_events.record_auth_event(user, "auth.mfa_host_recovered", target=user)
