"""Kiosk-named Station throttles; scopes are separate from the event Station's."""

from apps.makerspaces.station_throttles import (
    StationActorThrottle,
    StationIpThrottle,
    StationTokenThrottle,
)


class KioskStationPinTokenThrottle(StationTokenThrottle):
    scope = "kiosk_station_pin_token"


class KioskStationPinIpThrottle(StationIpThrottle):
    scope = "kiosk_station_pin_ip"


class KioskStationSessionThrottle(StationTokenThrottle):
    scope = "kiosk_station_session"


class KioskOperatorLeaseThrottle(StationActorThrottle):
    scope = "kiosk_operator_lease"


class KioskStationRevealThrottle(StationActorThrottle):
    """Fixed at 5/hour per user; reveal is also behind a current-password step-up."""

    scope = "kiosk_station_reveal"
