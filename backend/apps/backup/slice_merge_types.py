"""Value objects for the tenant-authorized delayed slice merge."""

from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Mapping
import uuid


class SliceMergeError(RuntimeError):
    """A delayed slice could not be merged without weakening fill-only safety."""


class SliceMergeInterrupted(BaseException):
    """A test/supervisor crash point; durable state remains resumable."""


@dataclass(frozen=True)
class SliceMergeInput:
    component_id: uuid.UUID
    ciphertext_path: Path
    identity_channel: BinaryIO


@dataclass(frozen=True)
class ValidatedSlice:
    component: object
    outer_fact: Mapping
    root: Path
    manifest: Mapping
    identity: bytearray


BoundaryHook = Callable[[str], None]


BOUNDARY_STAGED = "after_staging"
BOUNDARY_KEYS = "after_key_install"
BOUNDARY_ROWS = "after_row_apply"
BOUNDARY_OBJECTS = "after_object_promotion"
BOUNDARY_FINAL = "before_final_transaction"
