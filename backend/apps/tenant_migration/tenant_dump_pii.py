"""Source-mode and AAD-identity checks for Lane D raw PII transport."""

from dataclasses import dataclass

from django.apps import apps

from apps.encryption.crypto import is_envelope
from apps.encryption.registry import fields_for

from .tenant_dump_errors import TenantDumpVerificationError


PLAINTEXT = "plaintext"
ENCRYPTED = "encrypted"
SOURCE_PII_MODES = frozenset({PLAINTEXT, ENCRYPTED})


@dataclass(frozen=True)
class MappedPiiFindings:
    mapped_rows: int
    mapped_values: int
    empty_values: int
    envelope_values: int
    plaintext_values: int

    def as_manifest(self):
        return {
            "mapped_rows": self.mapped_rows,
            "mapped_values": self.mapped_values,
            "empty_values": self.empty_values,
            "envelope_values": self.envelope_values,
            "plaintext_values": self.plaintext_values,
        }


def source_pii_mode(enabled):
    return ENCRYPTED if enabled else PLAINTEXT


def scan_mapped_pii(rows_by_label, mode):
    """Classify raw mapped values without parsing or decrypting an envelope."""
    _require_mode(mode)
    mapped_rows = mapped_values = empty_values = envelope_values = 0
    for label, rows in sorted(rows_by_label.items()):
        model = apps.get_model(label)
        mapped = tuple(fields_for(model))
        if not mapped:
            continue
        for row in rows:
            mapped_rows += 1
            for item in mapped:
                field = model._meta.get_field(item.field_name)
                value = row[field.attname]
                mapped_values += 1
                if value in (None, "", b""):
                    empty_values += 1
                elif is_envelope(value):
                    envelope_values += 1

    plaintext_values = mapped_values - empty_values - envelope_values
    findings = MappedPiiFindings(
        mapped_rows=mapped_rows,
        mapped_values=mapped_values,
        empty_values=empty_values,
        envelope_values=envelope_values,
        plaintext_values=plaintext_values,
    )
    if mode == PLAINTEXT and envelope_values:
        raise TenantDumpVerificationError(
            "A plaintext Lane D source contains a mapped PII ciphertext envelope."
        )
    if mode == ENCRYPTED and plaintext_values:
        raise TenantDumpVerificationError(
            "An encrypted Lane D source contains a non-envelope mapped PII value."
        )
    return findings


def verify_ciphertext_aad_identities(
    source_rows, projected_rows, makerspace_id, *, mode
):
    """Refuse any makerspace or mapped-row PK change that would alter AES-GCM AAD."""
    _require_mode(mode)
    if mode == PLAINTEXT:
        return
    source_space = _makerspace_identity(source_rows)
    projected_space = _makerspace_identity(projected_rows)
    if source_space != makerspace_id or projected_space != source_space:
        raise TenantDumpVerificationError(
            "The encrypted Lane D makerspace primary key was remapped."
        )
    source = _mapped_identities(source_rows)
    projected = _mapped_identities(projected_rows)
    if source != projected:
        raise TenantDumpVerificationError(
            "A ciphertext-bearing Lane D row primary key was remapped."
        )


def _makerspace_identity(rows_by_label):
    rows = tuple(rows_by_label.get("makerspaces.Makerspace", ()))
    if len(rows) != 1:
        raise TenantDumpVerificationError(
            "The Lane D projection must contain exactly one source makerspace row."
        )
    return rows[0][apps.get_model("makerspaces.Makerspace")._meta.pk.attname]


def _mapped_identities(rows_by_label):
    result = {}
    for label, rows in sorted(rows_by_label.items()):
        model = apps.get_model(label)
        if not fields_for(model):
            continue
        pk_name = model._meta.pk.attname
        identities = tuple(sorted((row[pk_name] for row in rows), key=str))
        if len(identities) != len(set(identities)):
            raise TenantDumpVerificationError(
                "A Lane D mapped-row identity inventory contains a duplicate."
            )
        if identities:
            result[label] = identities
    return result


def _require_mode(mode):
    if mode not in SOURCE_PII_MODES:
        raise TenantDumpVerificationError("The Lane D source PII mode is invalid.")
