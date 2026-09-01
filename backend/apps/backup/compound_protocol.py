"""Version vocabulary shared by compound producers and host capability installers."""


PROTOCOL_FAMILY = "spaceworks-lane-e-b1-v"
PROTOCOL_VERSION_NUMBER = 1
PROTOCOL_VERSION = f"{PROTOCOL_FAMILY}{PROTOCOL_VERSION_NUMBER}"

# A host may eventually consume several producer versions. First ship supports
# exactly v1, but records a real closed range so widening is an explicit change.
SUPPORTED_PROTOCOL_MINIMUM = PROTOCOL_VERSION
SUPPORTED_PROTOCOL_MAXIMUM = PROTOCOL_VERSION
