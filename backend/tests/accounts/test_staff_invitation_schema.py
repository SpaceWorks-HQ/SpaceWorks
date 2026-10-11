"""Staff delivery responses include the one-time link in DRF and OpenAPI."""

import pytest
from drf_spectacular.generators import SchemaGenerator

from apps.accounts.serializers_staff_invitations import (
    StaffInvitationDeliverySerializer,
    StaffInvitationSerializer,
)


def test_delivery_serializer_extends_the_invitation_fields_without_secrets():
    fields = StaffInvitationDeliverySerializer().fields
    assert set(fields) == set(StaffInvitationSerializer.Meta.fields) | {
        "accept_url", "delivery_status",
    }
    assert not {"token_digest", "email_ciphertext", "created_by"} & set(fields)


@pytest.mark.django_db
def test_staff_invitation_delivery_openapi_documents_link_and_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    properties = schema["components"]["schemas"]["StaffInvitationDelivery"]["properties"]
    assert {"accept_url", "delivery_status", "role_name"} <= set(properties)
    for path, success in (
        ("/api/v1/admin/makerspaces/{makerspace_id}/staff-invitations", "201"),
        ("/api/v1/admin/makerspaces/{makerspace_id}/staff-invitations/{invitation_id}/resend", "200"),
    ):
        responses = schema["paths"][path]["post"]["responses"]
        assert {success, "400", "401", "403", "404", "429"} <= set(responses)
        assert responses[success]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/StaffInvitationDelivery",
        }
