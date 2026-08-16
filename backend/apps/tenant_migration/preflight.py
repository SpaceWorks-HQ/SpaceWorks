"""Fail-closed source checks for one-makerspace migration export."""

from dataclasses import dataclass

from django.apps import apps
from django.conf import settings
from django.db.models import Q

from apps.backup import storage
from apps.encryption import services
from apps.encryption.crypto import parse_envelope
from apps.encryption.models import MakerspaceEncryptionKey
from apps.encryption.registry import all_fields
from apps.payments.models import Payment


class SourcePreflightError(RuntimeError):
    """A source migration invariant failed before archive construction."""

    def __init__(self, check, detail):
        self.check = check
        super().__init__(f"Source migration preflight failed [{check}]: {detail}")


@dataclass(frozen=True)
class SourcePreflightResult:
    makerspace_id: int
    storage_mode: dict[str, str]
    carried_key_versions: tuple[tuple[int, str], ...]


def run_source_preflight(makerspace):
    """Validate that this source can produce a non-degrading migration archive."""
    if not settings.PII_ENCRYPTION_ENABLED:
        _fail(
            "encryption_enabled",
            "Only enabled-source migration is supported; mapped columns otherwise "
            "hold plaintext and PORTABLE export is unavailable.",
        )

    keys = _keys_for(makerspace)
    if sum(key.status == key.Status.ACTIVE for key in keys) != 1:
        _fail("exactly_one_active_key", "The makerspace must have exactly one ACTIVE key.")

    _check_live_envelopes(makerspace, keys)
    carried = [key for key in keys if key.status != key.Status.DISABLED]
    _check_brokers(carried)
    _check_live_checkouts(makerspace)
    try:
        storage_mode = {
            "private": storage.ensure_versioning_or_quiescence(
                settings.AWS_STORAGE_BUCKET_NAME
            ),
            "public_image": storage.ensure_versioning_or_quiescence(
                settings.PUBLIC_IMAGE_BUCKET
            ),
        }
    except Exception as exc:
        raise SourcePreflightError(
            "storage_mode", "Object-storage consistency could not be determined."
        ) from exc
    if any(mode not in {"versioned", "quiesced"} for mode in storage_mode.values()):
        _fail("storage_mode", "Object storage returned an unsupported consistency mode.")
    return SourcePreflightResult(
        makerspace_id=makerspace.pk,
        storage_mode=storage_mode,
        carried_key_versions=tuple((key.version, key.status) for key in keys),
    )


def _keys_for(makerspace):
    return list(
        MakerspaceEncryptionKey.objects.filter(makerspace=makerspace).order_by("version")
    )


def _check_live_envelopes(makerspace, keys):
    disabled_versions = {
        key.version for key in keys if key.status == key.Status.DISABLED
    }
    for field in all_fields():
        model = apps.get_model(field.model_label)
        tenant_lookup = field.makerspace_path.replace(".", "__")
        rows = model.objects.filter(**{tenant_lookup: makerspace.pk}).only(
            "pk", field.field_name
        )
        for row in rows.iterator(chunk_size=200):
            raw = row.__dict__.get(field.field_name)
            if not raw:
                continue
            try:
                version, _nonce, _ciphertext = parse_envelope(raw)
            except Exception as exc:
                raise SourcePreflightError(
                    "live_envelope_versions", "A mapped live value is not a valid envelope."
                ) from exc
            if version in disabled_versions:
                _fail(
                    "disabled_key_live_envelope",
                    f"A live envelope declares disabled key version {version}.",
                )


def _check_brokers(keys):
    for key in keys:
        try:
            services.broker_for_backend(key.broker_backend).unwrap_dek(
                key.wrapped_dek, key.makerspace_id, key.version
            )
        except Exception as exc:
            raise SourcePreflightError(
                "broker_readiness", f"Key version {key.version} cannot be unwrapped."
            ) from exc


def _check_live_checkouts(makerspace):
    checkout_state = (
        Q(external_order_id__isnull=False)
        | ~Q(checkout_url="")
        | Q(stripe_checkout_session_id__isnull=False)
        | ~Q(stripe_checkout_url="")
    )
    live = Payment.objects.filter(
        makerspace=makerspace,
        status=Payment.Status.PENDING,
        stripe_checkout_session_expired_at__isnull=True,
    ).filter(checkout_state)
    # Provider ids and checkout URLs are intentionally omitted from PORTABLE export.
    # Importing this row would mint a second payable checkout while the source link
    # remained live. The target cannot expire the old page because reconciliation
    # needs the omitted session/order id, so each deployment could see one settlement.
    if live.exists():
        _fail("unresolved_live_checkout", "A pending payment has a live checkout session.")


def _fail(check, detail):
    raise SourcePreflightError(check, detail)
