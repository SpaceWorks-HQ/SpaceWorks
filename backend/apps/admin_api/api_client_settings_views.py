from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics

from apps.accounts import rbac
from apps.admin_api.api_client_serializers import ApiIntegrationSettingsSerializer
from apps.admin_api.permissions import IsActiveStaff, require_action
from apps.audit import services as audit
from apps.makerspaces.models import Makerspace


@extend_schema(tags=["API clients"], summary="Retrieve or update API integration settings")
class ApiIntegrationSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = ApiIntegrationSettingsSerializer
    permission_classes = [IsActiveStaff]
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        makerspace_id = self.kwargs["makerspace_id"]
        require_action(self.request.user, rbac.Action.MANAGE_MAKERSPACE, makerspace_id)
        return get_object_or_404(Makerspace, pk=makerspace_id)

    def perform_update(self, serializer):
        instance = serializer.save()
        audit.record(
            self.request.user,
            "api_integration.updated",
            makerspace=instance,
            target=instance,
        )
