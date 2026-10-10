from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.events.serializers_public import PublicEventSerializer
from apps.payments.models import MakerspacePaymentSettings
from tests.events.test_public_api import list_url, make_event, make_space

pytestmark = pytest.mark.django_db


def test_public_list_exposes_paid_and_free_prices_and_configured_currency_without_secrets():
    space = make_space("public-prices")
    MakerspacePaymentSettings.objects.create(makerspace=space, default_currency="inr")
    make_event(space, "Paid", payment_amount=Decimal("125.50"))
    make_event(space, "Free", payment_amount=0)
    response = APIClient().get(list_url(space.slug))
    assert response.status_code == 200
    rows = {row["title"]: row for row in response.data}
    assert rows["Paid"]["payment_amount"] == "125.50"
    assert rows["Free"]["payment_amount"] == "0.00"
    assert {row["currency"] for row in rows.values()} == {"inr"}
    for row in rows.values():
        assert not {"payment_settings", "stripe_secret_key", "razorpay_key_secret", "provider"} & row.keys()


def test_public_price_uses_same_default_currency_as_charging_without_creating_settings():
    space = make_space("public-price-default")
    event = make_event(space, payment_amount=Decimal("8.25"))
    response = APIClient().get(list_url(space.slug))
    assert response.status_code == 200
    assert response.data[0]["currency"] == MakerspacePaymentSettings.for_makerspace(space).default_currency
    assert PublicEventSerializer(event).data["payment_amount"] == "8.25"
    assert not MakerspacePaymentSettings.objects.filter(makerspace=space).exists()


def test_organization_public_catalogue_inherits_event_price_and_host_currency():
    from apps.events.organizer_models import EventOrganizer
    from apps.organizations.models import Organization

    space = make_space("org-public-price")
    organization = Organization.objects.create(name="Builders", slug="builders", public_profile_enabled=True)
    event = make_event(space, payment_amount=Decimal("20.00"))
    MakerspacePaymentSettings.objects.create(makerspace=space, default_currency="eur")
    EventOrganizer.objects.create(event=event, organization=organization)
    response = APIClient().get(reverse("public-organization-events", kwargs={"slug": organization.slug}))
    assert response.status_code == 200
    assert response.data["results"][0]["payment_amount"] == "20.00"
    assert response.data["results"][0]["currency"] == "eur"
