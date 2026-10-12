"""Source-local snapshot columns that a tenant import must carry byte-for-byte.

``DeviceEvent.*_snapshot`` hold historical identifiers from the SOURCE deployment
(a device UUID string, a future command UUID, machine/request/batch integers). They are
not foreign keys and are never resolved: remapping one through ``TransactionPkMap``
would silently rebind history to whatever unrelated target row received that id. The
guard below keeps them out of every remap path; the live ``DeviceEvent.device`` FK and
the typed ``device_id`` audit metadata are what get remapped.
"""

from django.apps import apps

SOURCE_LOCAL_SNAPSHOT_FIELDS = frozenset(
    ("devices.DeviceEvent", name)
    for name in (
        "device_id_snapshot", "command_id_snapshot", "machine_id_snapshot",
        "service_request_id_snapshot", "qr_batch_id_snapshot",
    )
)


from .references_7b import PRINTER_SOURCE_SNAPSHOT_FIELDS

SOURCE_LOCAL_SNAPSHOT_FIELDS |= PRINTER_SOURCE_SNAPSHOT_FIELDS

from .references_7c import LABEL_SNAPSHOT_FIELDS

SOURCE_LOCAL_SNAPSHOT_FIELDS |= LABEL_SNAPSHOT_FIELDS


def validate_source_snapshot_fields(error_class, *, raw_scalar_references, exported_fields):
    for label, name in sorted(SOURCE_LOCAL_SNAPSHOT_FIELDS):
        field = apps.get_model(label)._meta.get_field(name)
        if field.is_relation:
            raise error_class(f"source snapshot became a relation: {label}.{name}")
        if (label, name) in raw_scalar_references:
            raise error_class(f"source snapshot is declared as a remapped scalar: {label}.{name}")
        if name not in exported_fields.get(label, "").split():
            raise error_class(f"source snapshot is not exported verbatim: {label}.{name}")
    actual = {
        (model._meta.label, field.name)
        for model in apps.get_app_config("devices").get_models()
        for field in model._meta.concrete_fields
        if field.name.endswith("_snapshot")
    }
    if actual != set(SOURCE_LOCAL_SNAPSHOT_FIELDS):
        raise error_class(
            f"device snapshot registry drifted; missing={sorted(actual - SOURCE_LOCAL_SNAPSHOT_FIELDS)}, "
            f"stale={sorted(SOURCE_LOCAL_SNAPSHOT_FIELDS - actual)}"
        )
