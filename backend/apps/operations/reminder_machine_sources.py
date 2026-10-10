"""Explicit, lazy adapters keep a tombstoned machine/maintenance app importable."""


def discover_certifications(makerspace, now, limit, local_tz):
    from apps.machines.reminders_certifications import discover
    return discover(makerspace, now, limit, local_tz)


def build_certification(makerspace, reminder, now, local_tz):
    from apps.machines.reminders_certifications import build
    return build(makerspace, reminder, now, local_tz)


def dispatch_certification(makerspace, reminder, message):
    from apps.machines.reminders_certifications import dispatch
    return dispatch(makerspace, reminder, message)


def discover_digest(makerspace, now, limit, local_tz):
    from apps.machines.reminders_certification_digest import discover
    return discover(makerspace, now, limit, local_tz)


def build_digest(makerspace, reminder, now, local_tz):
    from apps.machines.reminders_certification_digest import build
    return build(makerspace, reminder, now, local_tz)


def dispatch_digest(makerspace, reminder, message):
    from apps.machines.reminders_certification_digest import dispatch
    return dispatch(makerspace, reminder, message)


def discover_maintenance(makerspace, now, limit, local_tz):
    from apps.maintenance.reminders import discover
    return discover(makerspace, now, limit, local_tz)


def build_maintenance(makerspace, reminder, now, local_tz):
    from apps.maintenance.reminders import build
    return build(makerspace, reminder, now, local_tz)


def dispatch_maintenance(makerspace, reminder, message):
    from apps.maintenance.reminders import dispatch
    return dispatch(makerspace, reminder, message)
