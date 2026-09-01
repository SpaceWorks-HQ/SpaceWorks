"""Immutable policy types for the Lane D tenant-dump catalogs."""

from dataclasses import dataclass
from enum import StrEnum


class ModelDisposition(StrEnum):
    PRESERVE = "preserve"
    PRESERVE_LIVE = "preserve_live"
    PROJECT = "project"
    RESET = "reset"
    DROP = "drop"
    BOOTSTRAP = "bootstrap"
    EMPTY = "empty"
    REFUSE = "refuse"


class AuthorityDisposition(StrEnum):
    PRESERVE = "preserve"
    RESET = "reset"
    DROP = "drop"


@dataclass(frozen=True)
class ModelRule:
    disposition: ModelDisposition
    reason: str


@dataclass(frozen=True)
class AuthorityField:
    dispositions: tuple[AuthorityDisposition, ...]
    reason: str


@dataclass(frozen=True)
class NoAuthorityField:
    reason: str


@dataclass(frozen=True)
class TableRule:
    disposition: ModelDisposition
    reason: str


def authority(disposition, reason):
    if isinstance(disposition, AuthorityDisposition):
        dispositions = (disposition,)
    else:
        dispositions = tuple(disposition)
    return AuthorityField(dispositions=dispositions, reason=reason)
