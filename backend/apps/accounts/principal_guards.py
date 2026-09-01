"""Relational guards for inert system principals stored in ``accounts.User``."""

from rest_framework.exceptions import PermissionDenied


ANONYMOUS_REQUESTER_CREDENTIAL_ERROR = (
    "This is an anonymous-request system principal, not an account."
)
ANONYMOUS_REQUESTER_ACCESS_ERROR = (
    "An anonymous-request system principal's access status cannot be changed."
)


def is_anonymous_requester(user) -> bool:
    """Use the database-unique relationship, never a mutable username convention."""
    if user is None or user.pk is None:
        return False
    from apps.makerspaces.models import Makerspace

    return Makerspace.objects.filter(anonymous_requester_id=user.pk).exists()


def refuse_anonymous_requester_credential(user) -> None:
    if is_anonymous_requester(user):
        raise PermissionDenied(ANONYMOUS_REQUESTER_CREDENTIAL_ERROR)


def refuse_anonymous_requester_access_mutation(user) -> None:
    if is_anonymous_requester(user):
        raise PermissionDenied(ANONYMOUS_REQUESTER_ACCESS_ERROR)
