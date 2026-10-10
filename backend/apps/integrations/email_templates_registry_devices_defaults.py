"""Staff-only device notification wording, with no machine or credential context."""

DEFAULTS = {
    "offline": (
        "Device offline: {{ device.name }}",
        "Device {{ device.name }} ({{ device.kind }}, {{ device.id }}) is offline.\n"
        "Last seen: {{ device.last_seen_at }}\nOffline since: {{ device.offline_since }}",
    ),
    "recovered": (
        "Device recovered: {{ device.name }}",
        "Device {{ device.name }} ({{ device.kind }}, {{ device.id }}) has recovered.\n"
        "Last seen: {{ device.last_seen_at }}",
    ),
}
