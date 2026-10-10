import pytest

from apps.hardware_requests.checks import POSITIVE, check_replay_timing


@pytest.mark.parametrize("name", POSITIVE)
@pytest.mark.parametrize("value", [0, -1, True, "1"])
def test_replay_timing_rejects_nonpositive_and_noninteger_values(settings, name, value):
    setattr(settings, name, value)
    assert check_replay_timing()


def test_replay_age_cannot_outlive_tombstones_and_claim_timeout_is_shorter(settings):
    settings.KIOSK_COMMAND_MAX_AGE_SECONDS = settings.KIOSK_REPLAY_RETENTION_SECONDS + 1
    assert "hardware_requests.E106" in {error.id for error in check_replay_timing()}
    settings.KIOSK_COMMAND_MAX_AGE_SECONDS = settings.KIOSK_REPLAY_CLAIM_TIMEOUT_SECONDS
    assert "hardware_requests.E105" in {error.id for error in check_replay_timing()}


def test_default_replay_timing_is_valid():
    assert check_replay_timing() == []
