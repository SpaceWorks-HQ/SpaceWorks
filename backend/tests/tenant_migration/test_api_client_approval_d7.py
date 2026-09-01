import pytest

from apps.apiclients.origin_validation import validate_exact_origins


def test_exact_origin_validator_canonicalizes_and_deduplicates():
    assert validate_exact_origins([
        "https://EXAMPLE.test:443", "https://example.test"
    ]) == ["https://example.test"]


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.test/",
        "https://example.test/path",
        "https://user@example.test",
        "https://*.example.test",
        "https://example.test?query=1",
        "https://example.test#fragment",
    ],
)
def test_exact_origin_validator_refuses_non_origins_and_wildcards(origin):
    with pytest.raises(ValueError):
        validate_exact_origins([origin])
