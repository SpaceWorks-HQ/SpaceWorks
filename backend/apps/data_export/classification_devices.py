"""Device identity export classification (phase 7a).

Device identity/config and its append-only DeviceEvent history are tenant data. The
enrollment bearer and the replay nonces are live authentication material and never
travel: a moved or restored device must enroll again with fresh proof of possession.
"""

DEVICE_EXPORTED_MODEL_FIELDS = {
    "devices.Device": (
        "id makerspace kind name status public_key key_fingerprint key_version last_seen_at "
        "offline_threshold_seconds offline_since offline_notified_at created_by created_at "
        "revoked_at revoked_by"
    ),
    "devices.DeviceEvent": (
        "id makerspace device device_id_snapshot device_name device_key_version operation_id "
        "event_type outcome command_id_snapshot machine_id_snapshot service_request_id_snapshot "
        "qr_batch_id_snapshot details created_at"
    ),
}

DEVICE_OMITTED_MODELS = {
    "devices.DeviceEnrollment": (
        "Live device enrollment bearer authority; a target device must re-enroll."
    ),
    "devices.DeviceRequestNonce": "Deployment-local signed-request replay state.",
}
