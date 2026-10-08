"""Disposition vocabulary and the policy record every uniqueness rule is built from."""
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

class UniqueValueDisposition(StrEnum):
    DROP_ROW = "drop_row"
    OMITTED_FRESH = "omitted_fresh"
    OMITTED_NULL = "omitted_null"
    PRESERVE_OR_REGENERATE = "preserve_or_regenerate"
    REMAPPED_REFERENCE = "remapped_reference"
    SEEDED_RESOLUTION = "seeded_resolution"
    TARGET_CREATION = "target_creation"


ValueGenerator = Callable[[dict, object, object], object]


@dataclass(frozen=True)
class UniqueValuePolicy:
    disposition: UniqueValueDisposition
    reason: str
    collision_field: str | None = None
    generator: ValueGenerator | None = None


def _policy(disposition, reason, *, field=None, generator=None):
    return UniqueValuePolicy(disposition, reason, field, generator)


FRESH = UniqueValueDisposition.OMITTED_FRESH
NULL = UniqueValueDisposition.OMITTED_NULL
PRESERVE = UniqueValueDisposition.PRESERVE_OR_REGENERATE
REMAP = UniqueValueDisposition.REMAPPED_REFERENCE

