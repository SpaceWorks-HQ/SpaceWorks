"""WCAG contrast floor for the frontend theme tokens.

Lives here rather than in vitest for the same reason
``test_frontend_feature_definitions_match_the_backend`` does: the check has to read
a frontend source file, and ``docker-compose.dev.yml`` mounts ``./frontend`` into the
backend container read-only precisely so these guards can. Vitest cannot do it at all
-- CSS imports resolve to an empty string under its default config, ``?raw`` included.

This is a drift guard, not a one-off audit. The pastel theme is edited by hand, and a
token nudged a few points lighter silently drops body text below AA with nothing to
notice it. ``--color-muted`` had already drifted to 4.35:1 on ``--color-bg`` and
3.95:1 on ``--color-surface`` before this test existed.
"""

import re
from pathlib import Path

import pytest

INDEX_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"

AA_BODY_TEXT = 4.5
# WCAG 2.2 SC 2.4.11: a focus indicator must be distinguishable from its surround.
NON_TEXT = 3.0

BACKGROUNDS = ("bg", "surface", "panel")
# Every token that can style STANDALONE text on one of the three backgrounds. The three
# status inks were missing while the palette was effectively one colour and they only ever
# appeared inside solid pastel fills (where the fixed `on-*` tokens apply instead). The
# surface-coded palette gives them real standalone work, so an unguarded one could drift
# below AA exactly the way `--color-muted` silently had before this test existed.
TEXT_TOKENS = (
    "ink",
    "muted",
    "accent-ink",
    "secondary-ink",
    "success-ink",
    "warn-ink",
    "info-ink",
    "danger",
)
SCOPES = (("light", ":root {"), ("dark", ":root.dark {"))


def _css():
    if not INDEX_CSS.exists():  # pragma: no cover - host runs without the mount
        pytest.skip(f"{INDEX_CSS} is not readable from this test environment")
    # Strip comments first: the theme's own notes contain "{name}-ink", whose brace
    # would end the block scan early and hide every token declared after it.
    return re.sub(r"/\*.*?\*/", "", INDEX_CSS.read_text(encoding="utf-8"), flags=re.S)


def _block(css, selector):
    start = css.index(selector)
    return css[start:css.index("}", start)]


def _token(css, selector, name):
    match = re.search(rf"--color-{name}:\s*([\d\s]+);", _block(css, selector))
    assert match, f"--color-{name} is missing from {selector}"
    return tuple(int(part) for part in match.group(1).split())


def _luminance(rgb):
    def channel(value):
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("scope_name,selector", SCOPES)
@pytest.mark.parametrize("token", TEXT_TOKENS)
def test_text_tokens_meet_aa_on_every_background(scope_name, selector, token):
    css = _css()
    colour = _token(css, selector, token)
    for background in BACKGROUNDS:
        ratio = _contrast(colour, _token(css, selector, background))
        assert ratio >= AA_BODY_TEXT, (
            f"{scope_name}: --color-{token} on --color-{background} "
            f"is {ratio:.2f}:1, below the {AA_BODY_TEXT}:1 AA floor for body text."
        )


@pytest.mark.parametrize("scope_name,selector", SCOPES)
def test_focus_indicator_stands_out_from_every_background(scope_name, selector):
    css = _css()
    focus = _token(css, selector, "focus")
    for background in BACKGROUNDS:
        ratio = _contrast(focus, _token(css, selector, background))
        assert ratio >= NON_TEXT, (
            f"{scope_name}: --color-focus on --color-{background} "
            f"is {ratio:.2f}:1, below the {NON_TEXT}:1 floor for a focus indicator."
        )
