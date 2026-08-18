import pytest
from django.test import override_settings
from rest_framework.exceptions import ValidationError

from apps.hardware_requests.models import PublicToolLoan
from apps.hardware_requests.self_checkout_workflow import checkout_tool
from apps.hardware_requests.self_checkout_views import (
    PublicToolCheckoutView,
    PublicToolReturnView,
)
from apps.makerspaces.guards import require_feature
from tests.test_public_self_checkout import (
    checkout_payload,
    checkout_url,
    eligible_member,
    make_product,
    make_qr,
    make_space,
    member_client,
)

pytestmark = pytest.mark.django_db


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_response_omits_physical_target_labels():
    makerspace = make_space("checkout-public-shape")
    product = make_product(
        makerspace,
        name="Public Multimeter",
        public_self_checkout_enabled=True,
    )
    qr = make_qr(makerspace, product)

    user = eligible_member(makerspace, "checkout-public-shape-member")
    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, qr.payload),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PublicToolLoan.Status.CHECKED_OUT
    assert response.data["items"] == [{"product_name": product.name, "quantity": 1}]
    assert "target_type" not in response.data
    assert "target_label" not in response.data


@override_settings(API_CLIENT_AUTH_REQUIRED=False)
def test_public_checkout_rejects_overlong_qr_payload():
    makerspace = make_space("checkout-long-payload")

    user = eligible_member(makerspace, "checkout-long-payload-member")
    response = member_client(user).post(
        checkout_url(makerspace),
        checkout_payload(makerspace, user, "x" * 65),
        format="json",
    )

    assert response.status_code == 400
    assert "payload" in response.data


def test_public_self_checkout_views_use_dedicated_throttle_scopes():
    assert PublicToolCheckoutView.throttle_scope == "public_tool_checkout"
    assert PublicToolReturnView.throttle_scope == "public_tool_return"


def test_checkout_rechecks_feature_after_boundary_check():
    makerspace = make_space("checkout-feature-race")
    user = eligible_member(makerspace, "checkout-feature-race-member")
    require_feature(makerspace, "inventory.self_checkout")

    disabled_features = [
        key
        for key in makerspace.enabled_features
        if key != "inventory.self_checkout"
    ]
    type(makerspace).objects.filter(pk=makerspace.pk).update(
        enabled_features=disabled_features
    )

    with pytest.raises(ValidationError) as exc:
        checkout_tool(makerspace, user, "unused", evidence_id=0)

    assert exc.value.detail == {
        "feature": "inventory.self_checkout is disabled for this makerspace."
    }
    assert not PublicToolLoan.objects.exists()
