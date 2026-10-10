"""Managed host admission tracks saves/deletes; bulk updates obey the cache contract."""

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.makerspaces import hosting
from apps.makerspaces.models import Makerspace
from apps.makerspaces.provisioning import provision_subdomain
from tests.return_helpers import make_space

pytestmark = pytest.mark.django_db


@override_settings(PLATFORM_DOMAIN_SUFFIX=".managed.example", INFRA_HOSTS={"testserver"})
def test_managed_save_and_delete_invalidate_the_verified_domain_cache(django_capture_on_commit_callbacks):
    # Invalidation runs on commit; capture and execute those callbacks inside the test
    # transaction, as a real request's commit would.
    space = make_space("managed-cache")
    space.frontend_domain = "tools.example.org"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    with django_capture_on_commit_callbacks(execute=True):
        space.save()
    assert hosting.host_is_allowed("tools.example.org") is True
    space.frontend_domain = "lab.example.org"
    with django_capture_on_commit_callbacks(execute=True):
        space.save()
    assert hosting.host_is_allowed("tools.example.org") is False
    assert hosting.host_is_allowed("lab.example.org") is True
    # Makerspaces are never ORM-deleted (purge goes through the lifecycle service and a
    # protected PII fence); clearing the domain is the save path that must drop it.
    space.frontend_domain = ""
    with django_capture_on_commit_callbacks(execute=True):
        space.save()
    assert hosting.host_is_allowed("lab.example.org") is False


@override_settings(PLATFORM_DOMAIN_SUFFIX=".managed.example", INFRA_HOSTS={"testserver"})
def test_bulk_update_does_not_emit_save_signal_and_expired_cache_refetches():
    space = make_space("managed-cache-bulk")
    space.frontend_domain = "old.example.org"
    space.frontend_domain_status = Makerspace.DomainStatus.VERIFIED
    space.save()
    assert hosting.host_is_allowed("old.example.org") is True
    Makerspace.objects.filter(pk=space.pk).update(frontend_domain="new.example.org")
    assert hosting.host_is_allowed("old.example.org") is True
    # Cache expiry has the same read path as a missing key; do not wait five minutes.
    cache.delete(hosting.CACHE_KEY)
    assert hosting.host_is_allowed("old.example.org") is False
    assert hosting.host_is_allowed("new.example.org") is True


@override_settings(PLATFORM_DOMAIN_SUFFIX=".managed.example")
def test_managed_save_never_auto_verifies_a_pending_custom_domain():
    space = make_space("managed-pending-cache")
    space.frontend_domain = "unproven.example.org"
    space.frontend_domain_status = Makerspace.DomainStatus.PENDING
    space.save()
    space.refresh_from_db()
    assert space.frontend_domain_status == Makerspace.DomainStatus.PENDING
    assert hosting.host_is_allowed("unproven.example.org") is False


@pytest.mark.parametrize("suffix", ["not-a-suffix", ".invalid/path", ".invalid..example"])
def test_invalid_platform_suffix_is_refused_without_mutating_the_space(settings, suffix):
    settings.PLATFORM_DOMAIN_SUFFIX = suffix
    space = make_space("invalid-provision-suffix")
    with pytest.raises(ValidationError, match="suffix is invalid"):
        provision_subdomain(space, "lab", actor=None)
    space.refresh_from_db()
    assert not space.frontend_domain
