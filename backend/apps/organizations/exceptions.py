from rest_framework.exceptions import APIException


class OrganizationConflict(APIException):
    status_code = 409
    default_detail = "The organization state changed. Refresh and try again."
    default_code = "organization_conflict"

    def __init__(self, detail=None, code=None):
        super().__init__(
            {
                "detail": detail or self.default_detail,
                "code": code or self.default_code,
            }
        )


class InvitationExpired(OrganizationConflict):
    default_detail = "This invitation has expired."
    default_code = "invitation_expired"


class InvitationRevoked(OrganizationConflict):
    default_detail = "This invitation has been revoked."
    default_code = "invitation_revoked"


class InvitationRedeemed(OrganizationConflict):
    default_detail = "This invitation has already been redeemed."
    default_code = "invitation_redeemed"


class MembershipSuspended(OrganizationConflict):
    default_detail = "The existing organization membership is suspended."
    default_code = "organization_membership_suspended"


class InvitationGrantChanged(OrganizationConflict):
    default_detail = "The inviter no longer holds every proposed action."
    default_code = "invitation_grant_changed"
