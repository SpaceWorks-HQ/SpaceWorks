"""Synthetic trees for the DeviceAuthentication late-gate ordering contract (phase 7a)."""

from pathlib import Path

import pytest

from apps.tenant_migration.source_gate_guards import SourceGateCoverageError
from apps.tenant_migration.source_gate_http_guards import validate_authenticated_http_boundary

_DEVICE_VIEW = (
    "class SignedView:\n"
    "    authentication_classes = [DeviceAuthentication]\n"
    "    def post(self, request):\n"
    "        return mutate_tenant()\n"
)
_OK = (
    "class DeviceAuthentication:\n"
    "    def authenticate(self, request):\n"
    "        device = resolve()\n"
    "        request.selected_makerspace_id = device.makerspace_id\n"
    "        _assert_source_gate(request)\n"
    "        return device, None\n"
    "def _assert_source_gate(request):\n"
    "    assert_request_write_allowed(request)\n"
)
_SELECT = "        request.selected_makerspace_id = device.makerspace_id\n"
_GATE = "        _assert_source_gate(request)\n"


def _write(root, relative, content):
    target = Path(root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_a_singleton_device_authenticator_with_an_ordered_gate_is_admitted(tmp_path):
    _write(tmp_path, "devices/views_signed.py", _DEVICE_VIEW)
    _write(tmp_path, "devices/authentication.py", _OK)
    validate_authenticated_http_boundary(tmp_path, SourceGateCoverageError)


@pytest.mark.parametrize(
    "authentication, match",
    [
        (_OK.replace(_SELECT + _GATE, _GATE + _SELECT), "before selecting"),
        (_OK.replace(_GATE, ""), "never calls"),
        (_OK.replace("assert_request_write_allowed", "noop"), "does not assert"),
        (None, "module is missing"),
    ],
)
def test_a_device_authenticator_without_the_ordered_gate_is_refused(tmp_path, authentication, match):
    _write(tmp_path, "devices/views_signed.py", _DEVICE_VIEW)
    if authentication is not None:
        _write(tmp_path, "devices/authentication.py", authentication)
    with pytest.raises(SourceGateCoverageError, match=match):
        validate_authenticated_http_boundary(tmp_path, SourceGateCoverageError)


@pytest.mark.parametrize("authenticators", [
    "[DeviceAuthentication, SpaceWorksJWTAuthentication]",
    "[DeviceAuthentication, DeviceAuthentication]",
    "[UnknownAuthentication]",
])
def test_mixed_duplicated_or_unknown_authenticators_are_refused(tmp_path, authenticators):
    _write(tmp_path, "devices/views_signed.py", _DEVICE_VIEW.replace("[DeviceAuthentication]", authenticators))
    _write(tmp_path, "devices/authentication.py", _OK)
    with pytest.raises(SourceGateCoverageError, match="overrides"):
        validate_authenticated_http_boundary(tmp_path, SourceGateCoverageError)
