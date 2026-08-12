MACHINE_BEARING_STREAMS = frozenset({"printing", "maintenance"})

TYPE_OVERRIDABLE_AUDIENCES = {
    "printing": ("requester", "staff"),
    "maintenance": ("staff",),
}
