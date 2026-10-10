import pytest

from apps.payments.models import MakerspacePaymentSettings
from tests.return_helpers import authenticated_client, make_member, make_space

pytestmark = pytest.mark.django_db(transaction=True)


def route(lab):
    return f"/api/v1/admin/makerspace/{lab.pk}/profile"


@pytest.fixture
def profile():
    lab = make_space("profile-concurrency")
    manager = make_member("profile-concurrency-manager", lab)
    return lab, manager, authenticated_client(manager)


@pytest.mark.django_db(transaction=True)
def test_profile_currency_and_payment_settings_edits_serialize_without_losing_fields(profile):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection
    lab, manager, _ = profile
    payment = MakerspacePaymentSettings.objects.create(makerspace=lab)
    ready = Barrier(2)

    def patch(path, body):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
            ready.wait(timeout=10)
            return authenticated_client(manager).patch(path, body, format="json").status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(patch, route(lab), {"default_currency": "eur", "country": "IN"}),
                   pool.submit(patch, f"/api/v1/admin/makerspace/{lab.pk}/payment-settings", {"loan_grace_days": 3})]
        assert [result.result(timeout=30) for result in results] == [200, 200]
    payment.refresh_from_db()
    lab.refresh_from_db()
    assert (payment.default_currency, payment.loan_grace_days, lab.country) == ("eur", 3, "IN")


def test_first_profile_currency_save_serializes_with_first_payment_settings_save(profile, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection
    lab, manager, _ = profile
    ready = Barrier(2)
    validate_unique = MakerspacePaymentSettings.validate_unique

    def simultaneous_unique_checks(settings, *args, **kwargs):
        validate_unique(settings, *args, **kwargs)
        if settings._state.adding:
            # Both inserts pass model validation before contending on the DB's
            # one-to-one constraint. This exercises real creation/lock coordination.
            ready.wait(timeout=10)

    monkeypatch.setattr(MakerspacePaymentSettings, "validate_unique", simultaneous_unique_checks)

    def patch(path, body):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
            return authenticated_client(manager).patch(path, body, format="json").status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(patch, route(lab), {"default_currency": "eur"}),
                   pool.submit(patch, f"/api/v1/admin/makerspace/{lab.pk}/payment-settings", {"loan_grace_days": 3})]
        assert [result.result(timeout=30) for result in results] == [200, 200]
    payment = MakerspacePaymentSettings.objects.get(makerspace=lab)
    assert (payment.default_currency, payment.loan_grace_days) == ("eur", 3)
