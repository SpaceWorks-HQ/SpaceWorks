import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework import serializers as drf_serializers

from apps.admin_api.serializers_notification_destinations import (
    NotificationDestinationWriteSerializer,
)
from apps.integrations import webhooks
from apps.integrations.webhook_validation import (
    ResolvedAddress,
    ResolvedWebhookTarget,
    validate_webhook_url,
)


def _dns_answers(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            (address, 443, 0, 0) if ":" in address else (address, 443),
        )
        for address in addresses
    ]


@pytest.mark.parametrize("address", ["10.20.30.40", "169.254.169.254"])
def test_webhook_destination_save_rejects_private_and_link_local_dns(
    address, monkeypatch
):
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo",
        lambda *_args, **_kwargs: _dns_answers(address),
    )

    serializer = NotificationDestinationWriteSerializer(
        data={
            "channel": "slack",
            "label": "Unsafe room",
            "webhook_url": "https://hooks.customer.example/services/secret",
        }
    )

    assert serializer.is_valid() is False
    assert "webhook_url" in serializer.errors


def test_webhook_validation_rejects_when_any_dns_answer_is_private(monkeypatch):
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo",
        lambda *_args, **_kwargs: _dns_answers("93.184.216.34", "10.20.30.40"),
    )

    with pytest.raises(drf_serializers.ValidationError, match="non-public"):
        validate_webhook_url("https://hooks.customer.example/services/secret")


def test_webhook_redirect_to_link_local_dns_is_refused_before_second_post(monkeypatch):
    def resolve(_hostname, port, **_kwargs):
        address = (
            "169.254.169.254"
            if _hostname == "metadata.internal"
            else "93.184.216.34"
        )
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port),
            )
        ]

    post = Mock(return_value=(302, "https://metadata.internal/latest/meta-data"))
    monkeypatch.setattr(
        "apps.integrations.webhook_validation.socket.getaddrinfo", resolve
    )
    monkeypatch.setattr(webhooks, "_post_to_target", post)
    makerspace = SimpleNamespace(
        pk=123,
        get_slack_webhook_url=lambda: "https://hooks.customer.example/services/secret",
    )

    with pytest.raises(webhooks.WebhookDeliveryError):
        webhooks.send_webhook(makerspace, channel="slack", text="sensitive payload")

    assert post.call_count == 1


def test_pinned_connection_uses_validated_ip_but_tls_hostname(monkeypatch):
    address = ResolvedAddress(
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        ("93.184.216.34", 443),
    )
    target = ResolvedWebhookTarget(
        url="https://hooks.customer.example/services/secret",
        hostname="hooks.customer.example",
        port=443,
        host_header="hooks.customer.example",
        request_target="/services/secret",
        addresses=(address,),
    )
    raw_socket = Mock()
    context = Mock()
    wrapped_socket = object()
    context.wrap_socket.return_value = wrapped_socket
    monkeypatch.setattr(webhooks.socket, "socket", Mock(return_value=raw_socket))
    connection = webhooks._PinnedHTTPSConnection(target, address)
    connection._context = context

    connection.connect()

    raw_socket.connect.assert_called_once_with(("93.184.216.34", 443))
    context.wrap_socket.assert_called_once_with(
        raw_socket,
        server_hostname="hooks.customer.example",
    )
    assert connection.sock is wrapped_socket
