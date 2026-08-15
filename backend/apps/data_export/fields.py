"""Per-fidelity field dispositions built from the literal schema snapshot."""

from django.apps import apps

from .models import EXPORTED_MODEL_FIELDS
from .types import Emitted, Fidelity, Omitted, Redacted, Remapped, Transformed

USER_PROJECTIONS = {
    Fidelity.REDACTED: frozenset({"id", "username"}),
    Fidelity.PORTABLE: frozenset(
        {
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "display_name",
            "phone",
            "date_joined",
        }
    ),
}

ALWAYS_OMITTED = {
    ("apiclients.ApiClient", "client_id"): "A rebuild issues a fresh client identifier.",
    ("apiclients.ApiClient", "secret_encrypted"): "API client credential.",
    ("bookings.BookableSpace", "public_token"): "Source bearer/status token.",
    ("bookings.Booking", "public_token"): "Source bearer/status token.",
    ("events.Event", "public_token"): "Source bearer/status token.",
    ("events.EventRegistration", "checkin_token"): "Source check-in bearer token.",
    ("events.EventRegistration", "email_exact_hash"): "Deployment-local blind index.",
    ("events.EventRegistration", "email_hash_generation"): "Deployment-local key generation.",
    ("hardware_requests.HardwareRequest", "public_token"): "Source bearer/status token.",
    ("integrations.NotificationDestination", "webhook_url"): "Encrypted webhook credential.",
    ("machines.Machine", "camera_feed_url"): "May embed camera credentials.",
    ("machines.Machine", "legacy_print_printer_id"): "Retired cutover provenance.",
    ("machines.MachineConsumableAdjustment", "legacy_filament_adjustment_id"): "Retired cutover provenance.",
    ("machines.MachineConsumablePool", "legacy_filament_spool_id"): "Retired cutover provenance.",
    ("machines.MachineServiceRequest", "public_token"): "Source bearer/status token.",
    ("machines.MachineServiceRequest", "legacy_print_request_id"): "Retired cutover provenance.",
    ("machines.MachineUsageEntry", "legacy_manual_print_log_id"): "Retired cutover provenance.",
    ("machines.ServiceQueue", "legacy_print_bucket_id"): "Retired cutover provenance.",
    ("machines.ServiceRequestFile", "legacy_print_request_file_id"): "Retired cutover provenance.",
    ("makerspaces.Makerspace", "domain_verification_token"): "Source routing challenge.",
    ("makerspaces.Makerspace", "public_api_key"): "Source publishable tenant credential.",
    ("makerspaces.Makerspace", "telegram_bot_token"): "Encrypted integration credential.",
    ("makerspaces.Makerspace", "smtp_password"): "Encrypted integration credential.",
    ("makerspaces.Makerspace", "slack_webhook_url"): "Encrypted integration credential.",
    ("makerspaces.Makerspace", "mattermost_webhook_url"): "Encrypted integration credential.",
    ("makerspaces.Makerspace", "discord_webhook_url"): "Encrypted integration credential.",
    ("payments.MakerspacePaymentSettings", "stripe_publishable_key"): "Source payment credential.",
    ("payments.MakerspacePaymentSettings", "stripe_secret_key"): "Source payment credential.",
    ("payments.MakerspacePaymentSettings", "stripe_webhook_secret"): "Source payment credential.",
    ("payments.MakerspacePaymentSettings", "connect_account_id"): "Source provider account binding.",
    ("payments.MakerspacePaymentSettings", "razorpay_key_id"): "Source payment credential.",
    ("payments.MakerspacePaymentSettings", "razorpay_key_secret"): "Source payment credential.",
    ("payments.MakerspacePaymentSettings", "razorpay_webhook_secret"): "Source payment credential.",
    ("payments.Payment", "external_order_id"): "Source provider identifier.",
    ("payments.Payment", "external_payment_id"): "Source provider identifier.",
    ("payments.Payment", "checkout_url"): "Source checkout bearer URL.",
    ("payments.Payment", "stripe_connected_account_id"): "Source provider account binding.",
    ("payments.Payment", "stripe_checkout_session_id"): "Source provider session identifier.",
    ("payments.Payment", "stripe_checkout_url"): "Source checkout bearer URL.",
    ("payments.Payment", "stripe_checkout_session_expired_at"): "Source checkout session state.",
    ("payments.Payment", "stripe_payment_intent_id"): "Source provider identifier.",
}

FIVE_CONFIG_FIELDS = {
    ("makerspaces.Makerspace", "branding_config"),
    ("machines.MachineType", "capability_config"),
    ("machines.Machine", "type_payload"),
    ("machines.Machine", "service_file_policy"),
    ("machines.MachineServiceRequest", "capability_payload"),
}

CUSTOM_ANSWERS = {
    ("bookings.Booking", "custom_answers"),
    ("events.EventRegistration", "custom_answers"),
}

EXTERNAL_REFERENCES = {
    ("events.EventCollaborator", "event"),
    ("events.EventRegistration", "registered_via_makerspace"),
    ("events.EventRegistration", "payment_via_makerspace"),
    ("operations.StockTransfer", "source_container"),
    ("operations.StockTransfer", "destination_container"),
    ("operations.StockTransfer", "source_makerspace"),
    ("operations.StockTransfer", "destination_makerspace"),
    ("payments.Payment", "via_makerspace"),
}

SAFE_TRANSFORMS = {
    ("makerspaces.Makerspace", "map_url"): "Strip userinfo, query and fragment.",
    ("makerspaces.Makerspace", "theme_config"): "Emit the reviewed display-key projection.",
    ("procurement.ToBuyItem", "link"): "Strip userinfo, query and fragment.",
}


def _field_disposition(fidelity: Fidelity, label: str, field_name: str):
    pair = (label, field_name)
    if pair in ALWAYS_OMITTED:
        return Omitted(ALWAYS_OMITTED[pair])
    if pair in FIVE_CONFIG_FIELDS and fidelity is Fidelity.REDACTED:
        return Omitted("Operator-authored JSON configuration is omitted from readable exports.")
    if pair == ("audit.AuditLog", "meta") and fidelity is Fidelity.REDACTED:
        return Redacted("meta_redacted")
    if pair in CUSTOM_ANSWERS and fidelity is Fidelity.REDACTED:
        return Redacted("custom_answers_redacted")
    if pair in SAFE_TRANSFORMS and fidelity is Fidelity.REDACTED:
        return Transformed(SAFE_TRANSFORMS[pair])
    if pair in EXTERNAL_REFERENCES and fidelity is Fidelity.PORTABLE:
        return Transformed("Snapshot an external reference; never follow it.")

    model = apps.get_model(label)
    model_field = model._meta.get_field(field_name)
    if fidelity is Fidelity.PORTABLE and (model_field.primary_key or model_field.is_relation):
        return Remapped()
    return Emitted()


FIELDS = {}
for _fidelity in Fidelity:
    for _label, _names in EXPORTED_MODEL_FIELDS.items():
        for _name in _names.split():
            FIELDS[(_fidelity, _label, _name)] = _field_disposition(
                _fidelity, _label, _name
            )

    _user = apps.get_model("accounts.User")
    for _field in _user._meta.get_fields():
        if not (_field.concrete or _field.many_to_many):
            continue
        if _field.name in USER_PROJECTIONS[_fidelity]:
            disposition = (
                Remapped()
                if _fidelity is Fidelity.PORTABLE and _field.primary_key
                else Emitted()
            )
        else:
            disposition = Omitted("Outside the literal global-user projection.")
        FIELDS[(_fidelity, "accounts.User", _field.name)] = disposition
