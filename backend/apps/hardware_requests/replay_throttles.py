from apps.makerspaces.station_throttles import StationTokenThrottle, StationIpThrottle


class ReplayPrepareThrottle(StationTokenThrottle):
    scope = "kiosk_replay_prepare"


class ReplayExecuteThrottle(StationTokenThrottle):
    scope = "kiosk_replay_execute"


class ReplayPrepareIpThrottle(StationIpThrottle):
    scope = "kiosk_replay_prepare"


class ReplayExecuteIpThrottle(StationIpThrottle):
    scope = "kiosk_replay_execute"
