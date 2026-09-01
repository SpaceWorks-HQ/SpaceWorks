import pytest
from rest_framework.exceptions import ValidationError

from apps.machines.service_consumable_pools import create_pool
from tests.return_helpers import make_space, make_user


pytestmark = pytest.mark.django_db


def test_create_pool_normalizes_display_hex_without_changing_semantic_colour():
    space = make_space("pool-display-colour")
    actor = make_user("pool-display-colour-actor")

    pool = create_pool(
        space,
        actor,
        material="PLA",
        color="Blue",
        color_hex="  #AABBCC  ",
        initial_grams="100",
    )

    assert pool.color == "Blue"
    assert pool.color_hex == "#aabbcc"


@pytest.mark.parametrize("color_hex", ["aabbcc", "#abcd", "#gg0000", "#1234567"])
def test_create_pool_rejects_malformed_display_hex(color_hex):
    space = make_space(f"bad-pool-display-{color_hex.replace('#', 'hex')}")
    actor = make_user(f"bad-pool-display-actor-{color_hex.replace('#', 'hex')}")

    with pytest.raises(ValidationError) as error:
        create_pool(
            space,
            actor,
            material="PLA",
            color="Blue",
            color_hex=color_hex,
            initial_grams="100",
        )

    assert "color_hex" in error.value.detail
