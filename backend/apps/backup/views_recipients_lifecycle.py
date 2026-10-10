"""Recipient revocation, compromise and reactivation."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.backup import recipients
from apps.backup.models import MakerspaceArchiveRecipient
from apps.backup.serializers_recipients import ArchiveRecipientSerializer
from apps.backup.views_recipients_common import (
    LIFECYCLE_RESPONSES, _recipient, _validation_response,
)


class ArchiveRecipientLifecycleView(APIView):
    permission_classes = [IsActiveStaff]
    operation = None
    module_gated = True

    def post(self, request, makerspace_id, pk):
        recipient = _recipient(request, makerspace_id, pk, module_gated=self.module_gated)
        try:
            recipient = self.operation(recipient=recipient, actor=request.user)
        except DjangoValidationError as exc:
            return _validation_response(exc)
        except MakerspaceArchiveRecipient.DoesNotExist as exc:
            raise Http404 from exc
        return Response(ArchiveRecipientSerializer(recipient).data)


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Revoke an archive recipient",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientRevokeView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.revoke_recipient)


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Mark an archive recipient as compromised",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientCompromiseView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.compromise_recipient)
    # Never module-gated: marking a leaked key compromised is security response, and
    # that must work even after the tenant switched the `backup` module off.
    module_gated = False


@extend_schema_view(
    post=extend_schema(
        tags=["Backup recipients"],
        summary="Reactivate a revoked archive recipient",
        request=None,
        responses=LIFECYCLE_RESPONSES,
    )
)
class ArchiveRecipientReactivateView(ArchiveRecipientLifecycleView):
    operation = staticmethod(recipients.reactivate_recipient)
