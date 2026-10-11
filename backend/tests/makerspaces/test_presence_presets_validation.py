"""Unconfigured presence settings round-trip without relaxing explicit bounds."""
import pytest
from django.core.exceptions import ValidationError

from apps.makerspaces.models import Makerspace, presence_presets
from apps.makerspaces.validators import DEFAULT_PRESENCE_PRESETS, validate_presence_presets


def test_empty_presence_presets_use_the_model_defaults():
    assert validate_presence_presets([]) == []
    assert presence_presets(Makerspace(presence_preset_minutes=[])) == DEFAULT_PRESENCE_PRESETS


def test_explicit_presence_presets_keep_their_values():
    assert validate_presence_presets([15, 90, 480]) == [15, 90, 480]


@pytest.mark.parametrize("value", [None, {}, "", [True], [14], [481], [60.0], [60, 60]])
def test_invalid_presence_presets_are_still_refused(value):
    with pytest.raises(ValidationError):
        validate_presence_presets(value)
