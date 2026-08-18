"""Shared client-IP resolution for DRF throttles and django-axes."""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.settings import api_settings
from rest_framework.throttling import BaseThrottle


def get_throttle_client_ip(request):
    """Resolve exactly the identity DRF uses for its configured proxy count."""
    if settings.AXES_IPWARE_PROXY_COUNT != api_settings.NUM_PROXIES:
        raise ImproperlyConfigured(
            "AXES_IPWARE_PROXY_COUNT and REST_FRAMEWORK['NUM_PROXIES'] must match."
        )
    return BaseThrottle().get_ident(request)
