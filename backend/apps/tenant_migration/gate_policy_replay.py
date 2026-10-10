"""Exact replay writer participation; no source-gate exemptions."""

REPLAY_HTTP_PARTICIPANTS = {
    "apps.hardware_requests.replay_views.KioskReplayPrepareView.post": "Path-bound Station tenant boundary before coordination/evidence writes.",
    "apps.hardware_requests.replay_views.KioskReplayExecuteView.post": "Path-bound Station tenant boundary spans claim, S3 and domain commit.",
}
REPLAY_TASK_PARTICIPANTS = {
    "apps.hardware_requests.tasks_replay.cleanup_replay_commands_task": "Per-tenant skip-and-count replay cleanup.",
}
REPLAY_FANOUT_PARTICIPANTS = {
    "apps.hardware_requests.replay_cleanup.cleanup_replay_commands": "Expired replay coordination cleanup.",
}
