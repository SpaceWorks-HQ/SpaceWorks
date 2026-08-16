"""Bounded OIDC discovery and authorization-code exchange."""

import json
import time
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.cache import cache


class OidcProviderUnavailable(Exception):
    pass


class OidcTokenRejected(Exception):
    pass


def discover(provider):
    cache_key = (
        f"oidc-discovery:{provider.pk}:{provider.updated_at.timestamp()}:"
        f"{provider.issuer}"
    )
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return cached
    suffix = ".well-known/openid-configuration"
    url = (
        f"{provider.issuer}{suffix}"
        if provider.issuer.endswith("/")
        else f"{provider.issuer}/{suffix}"
    )
    document = _json_request("get", url, unavailable=OidcProviderUnavailable)
    if document.get("issuer") != provider.issuer:
        raise OidcProviderUnavailable()
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _is_https_endpoint(document.get(name)):
            raise OidcProviderUnavailable()
    cache.set(
        cache_key,
        document,
        max(1, min(int(settings.OIDC_DISCOVERY_CACHE_SECONDS), 3600)),
    )
    return document


def exchange_code(provider, document, *, code, redirect_uri, code_verifier):
    payload = _json_request(
        "post",
        document["token_endpoint"],
        unavailable=OidcProviderUnavailable,
        rejected=OidcTokenRejected,
        data={
            "grant_type": "authorization_code",
            "client_id": provider.client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        },
    )
    if payload.get("error") or not isinstance(payload.get("id_token"), str):
        raise OidcTokenRejected()
    token = payload["id_token"].strip()
    if not token or len(token) > 16384:
        raise OidcTokenRejected()
    return token


def _json_request(method, url, *, unavailable, rejected=None, data=None):
    started = time.monotonic()
    try:
        response = getattr(requests, method)(
            url,
            data=data,
            timeout=settings.OIDC_HTTP_TIMEOUT_SECONDS,
            stream=True,
            allow_redirects=False,
        )
        if time.monotonic() - started > settings.OIDC_HTTP_TIMEOUT_SECONDS:
            raise unavailable()
        length = int(response.headers.get("Content-Length") or 0)
        if length > settings.OIDC_HTTP_MAX_BYTES:
            raise unavailable()
        body = response.raw.read(settings.OIDC_HTTP_MAX_BYTES + 1)
        if len(body) > settings.OIDC_HTTP_MAX_BYTES:
            raise unavailable()
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        if response.status_code != 200:
            if (
                rejected is not None
                and 400 <= response.status_code < 500
                and payload.get("error")
            ):
                raise rejected()
            raise unavailable()
        return payload
    except unavailable:
        raise
    except (requests.RequestException, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise unavailable() from exc


def _is_https_endpoint(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )
