"""The authenticated device principal handed to DRF as ``request.user``.

It is deliberately NOT an ``accounts.User``: it carries no roles, never reaches
``accounts.rbac`` and is never an audit actor. Views that accept it gate on the device
route registry instead.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DevicePrincipal:
    device_id: UUID
    makerspace_id: int
    kind: str
    key_version: int
    name: str

    is_authenticated = True
    is_anonymous = False

    @classmethod
    def from_device(cls, device):
        return cls(device.pk, device.makerspace_id, device.kind, device.key_version, device.name)
