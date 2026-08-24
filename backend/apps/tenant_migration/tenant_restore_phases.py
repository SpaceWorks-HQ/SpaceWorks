"""Ordered phase declarations for the resumable Lane D target restore."""

from .tenant_restore_objects import object_phases


BASE_PHASES_BEFORE_OBJECTS = (
    "static-preflight",
    "persist-offline",
    "exclude-image-writers",
)
BASE_PHASES_AFTER_FENCE = (
    "sibling-allocation",
    "database-restore",
    "target-state-and-cryptography",
    "object-prefix-reservation",
)
BASE_PHASES_AFTER_OBJECTS = (
    "api-client-reissue",
    "target-superadmin",
    "activation-verify",
    "activation-cutover",
    "activation-clear-gates",
    "activation-start-serving",
    "finalize",
)


def ordered_phases(inputs, *, external_scheduler):
    fence = (
        ("external-scheduler-stop", "external-scheduler-fence")
        if external_scheduler else ()
    )
    return (
        *BASE_PHASES_BEFORE_OBJECTS,
        *fence,
        *BASE_PHASES_AFTER_FENCE,
        *object_phases(inputs.object_entries),
        *BASE_PHASES_AFTER_OBJECTS,
    )
