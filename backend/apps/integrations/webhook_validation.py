"""Resolve and validate tenant-configured chat webhook destinations."""

import socket
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import SplitResult, urlsplit

from rest_framework import serializers


class UnsafeWebhookUrl(ValueError):
    """The URL is malformed, unresolvable, or reaches a non-public network."""


@dataclass(frozen=True)
class ResolvedAddress:
    family: int
    socktype: int
    proto: int
    sockaddr: tuple


@dataclass(frozen=True)
class ResolvedWebhookTarget:
    url: str
    hostname: str
    port: int
    host_header: str
    request_target: str
    addresses: tuple[ResolvedAddress, ...]


def _parse_url(raw: str) -> tuple[SplitResult, int]:
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname
    except ValueError as exc:
        raise UnsafeWebhookUrl("Enter a valid absolute https:// webhook URL.") from exc
    if parts.scheme != "https" or not hostname:
        raise UnsafeWebhookUrl("Enter an absolute https:// webhook URL.")
    if parts.username or parts.password or "@" in parts.netloc:
        raise UnsafeWebhookUrl("Webhook URL must not embed credentials.")
    if parts.fragment:
        raise UnsafeWebhookUrl("Webhook URL must not contain a fragment.")
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise UnsafeWebhookUrl("Webhook URL contains an invalid port.") from exc
    return parts, port


def _is_forbidden_address(raw_address: str) -> bool:
    address = ip_address(raw_address.split("%", 1)[0])
    if getattr(address, "ipv4_mapped", None) is not None:
        address = address.ipv4_mapped
    return any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def resolve_webhook_target(value: str) -> ResolvedWebhookTarget:
    """Resolve any public HTTPS host once and return only its pinned addresses."""
    raw = (value or "").strip()
    if not raw:
        raise UnsafeWebhookUrl("Webhook URL is blank.")
    parts, port = _parse_url(raw)

    try:
        answers = socket.getaddrinfo(
            parts.hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except (OSError, UnicodeError) as exc:
        raise UnsafeWebhookUrl("Webhook hostname could not be resolved.") from exc
    if not answers:
        raise UnsafeWebhookUrl("Webhook hostname could not be resolved.")

    addresses = []
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise UnsafeWebhookUrl("Webhook hostname returned an invalid address.")
        try:
            forbidden = _is_forbidden_address(sockaddr[0])
        except ValueError as exc:
            raise UnsafeWebhookUrl(
                "Webhook hostname returned an invalid address."
            ) from exc
        if forbidden:
            raise UnsafeWebhookUrl("Webhook hostname resolves to a non-public address.")
        key = (family, socktype, proto, sockaddr)
        if key not in seen:
            seen.add(key)
            addresses.append(ResolvedAddress(family, socktype, proto, sockaddr))

    request_target = parts.path or "/"
    if parts.query:
        request_target = f"{request_target}?{parts.query}"
    return ResolvedWebhookTarget(
        url=raw,
        hostname=parts.hostname,
        port=port,
        host_header=parts.netloc,
        request_target=request_target,
        addresses=tuple(addresses),
    )


def validate_webhook_url(value):
    """Blank clears; otherwise require a resolvable public HTTPS destination."""
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        resolve_webhook_target(raw)
    except UnsafeWebhookUrl as exc:
        raise serializers.ValidationError(str(exc)) from exc
    return raw
