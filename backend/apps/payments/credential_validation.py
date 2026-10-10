from cryptography.fernet import InvalidToken
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction

from apps.payments import stripe_client
from apps.payments.checkout_expiry import forget_closed_checkout


RAW_CREDENTIAL_FIELDS = ("stripe_secret_key", "stripe_webhook_secret")
PENDING_RAW_CREDENTIAL_ERROR = (
    "Cannot change raw Stripe credentials while raw Stripe sessions are pending."
)
PENDING_CONNECT_CREDENTIAL_ERROR = (
    "Cannot change platform Stripe credentials while Connect sessions are pending."
)


def validate_raw_credential_changes(
    payment_settings, changes, *, persist_closed=False
):
    """Reject supplied raw credential mutations that would strand pending sessions."""
    if payment_settings is None or not payment_settings.pk:
        return

    changed_fields = []
    for field in RAW_CREDENTIAL_FIELDS:
        if field not in changes:
            continue
        try:
            current_value = getattr(payment_settings, f"get_{field}")()
        except (ImproperlyConfigured, InvalidToken):
            current_value = None
        if changes[field] != current_value:
            changed_fields.append(field)
    if not changed_fields:
        return

    from apps.payments.models import Payment

    if persist_closed:
        possibly_live_sessions_exist = _potentially_live_sessions_exist(
            provider=Payment.StripeProvider.RAW,
            makerspace=payment_settings.makerspace,
            persist_closed=True,
        )
    else:
        # Boundary validation must stay local and fast. The locked update path
        # performs the authoritative Stripe check for terminal sessions.
        possibly_live_sessions_exist = Payment.objects.filter(
            makerspace=payment_settings.makerspace,
            stripe_provider=Payment.StripeProvider.RAW,
            status=Payment.Status.PENDING,
            stripe_checkout_session_id__isnull=False,
            stripe_checkout_session_expired_at__isnull=True,
        ).exists()
    if possibly_live_sessions_exist:
        raise ValidationError(
            {field: PENDING_RAW_CREDENTIAL_ERROR for field in changed_fields}
        )


def raw_credential_is_unreadable(payment_settings, field):
    if payment_settings is None or not payment_settings.pk:
        return False
    try:
        getattr(payment_settings, f"get_{field}")()
    except (ImproperlyConfigured, InvalidToken):
        return True
    return False


def update_payment_settings(payment_settings, changes):
    """Validate and persist settings while holding the checkout coordination lock."""
    from apps.payments.models import MakerspacePaymentSettings

    with transaction.atomic():
        if payment_settings.pk:
            # Lock order matches checkout: settings first, then any Payment query.
            # Holding this row through validation and save closes the gap where a
            # checkout session could otherwise appear before credential commit.
            locked = (
                MakerspacePaymentSettings.objects.select_for_update()
                .select_related("makerspace")
                .get(pk=payment_settings.pk)
            )
        else:
            locked = payment_settings
        credential_changes = {
            field: changes[field] for field in RAW_CREDENTIAL_FIELDS if field in changes
        }
        validate_raw_credential_changes(
            locked, credential_changes, persist_closed=True
        )
        for field, value in changes.items():
            setter = getattr(locked, f"set_{field}", None)
            if field in RAW_CREDENTIAL_FIELDS and setter is not None:
                setter(value)
            else:
                setattr(locked, field, value)
        locked.save()
        return locked


def _potentially_live_sessions_exist(
    *, provider, makerspace=None, persist_closed=False
):
    from apps.payments.models import Payment
    from apps.payments.resolution import source_for_payment

    sessions = Payment.objects.filter(
        stripe_provider=provider,
        stripe_checkout_session_id__isnull=False,
        stripe_checkout_session_expired_at__isnull=True,
    ).exclude(status=Payment.Status.PAID_ONLINE)
    if makerspace is not None:
        sessions = sessions.filter(makerspace=makerspace)
    if persist_closed:
        sessions = sessions.select_for_update()

    confirmed_closed = []
    for payment in sessions:
        source = source_for_payment(payment)
        if source is None:
            return True
        try:
            is_closed = stripe_client.checkout_session_is_closed(
                source, payment.stripe_checkout_session_id
            )
        except Exception:
            is_closed = False
        if not is_closed:
            return True
        confirmed_closed.append(payment)

    if persist_closed:
        for payment in confirmed_closed:
            payment.save(update_fields=[*forget_closed_checkout(payment), "updated_at"])
    return False

def validate_platform_credential_changes(
    platform_settings, changes, *, persist_closed=False
):
    """Reject platform credential mutations that would strand Connect sessions."""
    changed_fields = []
    for field in RAW_CREDENTIAL_FIELDS:
        if field not in changes:
            continue
        try:
            current_value = getattr(platform_settings, f"get_{field}")()
        except Exception:
            current_value = None
        if changes[field] != current_value:
            changed_fields.append(field)
    if not changed_fields:
        return

    from apps.payments.models import Payment

    if persist_closed:
        possibly_live_sessions_exist = _potentially_live_sessions_exist(
            provider=Payment.StripeProvider.CONNECT,
            persist_closed=True,
        )
    else:
        possibly_live_sessions_exist = Payment.objects.filter(
            stripe_provider=Payment.StripeProvider.CONNECT,
            status=Payment.Status.PENDING,
            stripe_checkout_session_id__isnull=False,
            stripe_checkout_session_expired_at__isnull=True,
        ).exists()
    if possibly_live_sessions_exist:
        raise ValidationError(
            {field: PENDING_CONNECT_CREDENTIAL_ERROR for field in changed_fields}
        )


def update_platform_payment_settings(platform_settings, changes):
    """Lock, validate, encrypt, and persist the singleton platform settings row."""
    from apps.payments.models import PlatformStripeConnectSettings

    with transaction.atomic():
        PlatformStripeConnectSettings.objects.get_or_create(pk=1)
        locked = PlatformStripeConnectSettings.objects.select_for_update().get(pk=1)
        credential_changes = {
            field: changes[field] for field in RAW_CREDENTIAL_FIELDS if field in changes
        }
        validate_platform_credential_changes(
            locked, credential_changes, persist_closed=True
        )
        for field, value in changes.items():
            setter = getattr(locked, f"set_{field}", None)
            if field in RAW_CREDENTIAL_FIELDS and setter is not None:
                setter(value)
            else:
                setattr(locked, field, value)
        locked.save()
        return locked
