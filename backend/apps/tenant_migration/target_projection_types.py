"""Typed target-owned projection declarations."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum

from django.apps import apps


class RowDisposition(StrEnum):
    DROP = "drop"
    PRESERVE_LIVE = "preserve_live"
    STAGE_INERT = "stage_inert"
    KEEP_TARGET = "keep_target"
    RESOLVE = "resolve"


class ReferenceDisposition(StrEnum):
    DROP_ROW = "drop_row"
    REMAP_RESOLVED = "remap_resolved"
    REMAP_TARGET_MEMBER = "remap_target_member"


@dataclass(frozen=True)
class TargetField:
    value: object = None
    use_model_default: bool = False
    resolver: Callable[[], object] | None = None
    allow_superadmin_override: bool = False
    condition: tuple[str, object] | None = None
    reason: str = ""

    def resolved_value(self, model_label: str, field_name: str):
        # A `resolver` asks the owning registry directly; `use_model_default` reads the
        # column's default. They are NOT interchangeable for capability fields. The test
        # suite patches the `enabled_modules` FIELD DEFAULT to the `everything` profile
        # (see tests/conftest.py), while `default_enabled_modules()` keeps answering the
        # real opt-in set -- so resolving capabilities from the field default would make
        # this projection hand an imported tenant whatever a default happens to say, and
        # would silently grant it every module under the test fixture. Capability policy
        # has one authority, and it is the module registry.
        if self.resolver is not None:
            return self.resolver()
        if self.use_model_default:
            return apps.get_model(model_label)._meta.get_field(field_name).get_default()
        return deepcopy(self.value)


@dataclass(frozen=True)
class RowPolicy:
    disposition: RowDisposition
    reason: str
    condition: tuple[str, object] | None = None


@dataclass(frozen=True)
class SeededResolution:
    lookup_fields: tuple[str, ...]
    archive_update_fields: tuple[str, ...]
    reason: str
    definition_fingerprint_fields: tuple[str, ...] = ()

    def archived_updates(self, archived_row):
        return {
            field: archived_row[field]
            for field in self.archive_update_fields
            if field in archived_row
        }


@dataclass(frozen=True)
class ForeignKeyPolicy:
    disposition: ReferenceDisposition
    reason: str


