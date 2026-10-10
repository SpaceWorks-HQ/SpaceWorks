"""WCAG sRGB maths and the public/member secondary-colour contract.

Keep in sync with frontend/src/lib/brandColours.ts. The stored fill is preserved;
foreground and interaction variants are derived, and link ink adapts to each mode.
"""

SURFACES = {
    "light": ((250, 249, 244), (239, 238, 233), (255, 255, 255)),
    "dark": ((22, 22, 28), (38, 40, 51), (29, 30, 38)),
}
PRODUCT_FILL = (249, 168, 212)
BODY_TEXT = {
    "light": ((31, 46, 53), (92, 103, 112)),
    "dark": ((236, 234, 242), (154, 160, 173)),
}
FIXED_INKS = {
    "light": ((0, 55, 74), (0, 50, 27), (61, 52, 0), (164, 36, 59)),
    "dark": ((125, 211, 252), (116, 221, 156), (252, 223, 70), (244, 114, 127)),
}
FIXED_FILLS = ((125, 211, 252), (116, 221, 156), (252, 223, 70))


def rgb(value):
    digits = value.lstrip("#")
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)
    return tuple(int(digits[index:index + 2], 16) for index in (0, 2, 4))


def luminance(color):
    def linear(channel):
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sum(linear(channel) * weight for channel, weight in zip(color, (.2126, .7152, .0722)))


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def blend(a, b, amount, rounded=True):
    # JS Math.round for nonnegative RGB channels (Python round ties to even).
    channels = tuple(x * (1 - amount) + y * amount for x, y in zip(a, b))
    return tuple(int(channel + .5) for channel in channels) if rounded else channels


def derive_palette(theme, mode):
    custom = bool(theme.get("primary_color") or theme.get("accent_color"))
    fill = rgb(theme["primary_color"]) if theme.get("primary_color") else PRODUCT_FILL
    foreground = max(((0, 0, 0), (255, 255, 255)), key=lambda color: contrast(color, fill)) if custom else (90, 22, 51)
    target = (255, 255, 255) if foreground == (0, 0, 0) else (0, 0, 0)
    hover, active = (blend(fill, target, .08), blend(fill, target, .16)) if custom else (fill, fill)
    surfaces = SURFACES[mode]
    # Muted body text also appears inside public/member tint blocks. Reduce the
    # tint strength rather than altering the product text/status/focus tokens.
    tint_alphas = []
    for requested in (.1, .15):
        for step in range(101):
            alpha = requested * (1 - step / 100)
            if all(contrast(text, blend(surface, fill, alpha, False)) >= 4.55
                   for text in (*BODY_TEXT[mode], *FIXED_INKS[mode]) for surface in surfaces):
                tint_alphas.append(alpha)
                break
    backgrounds = [
        (f"{name}{suffix}", background)
        for name, surface in zip(("bg", "surface", "panel"), surfaces)
        for suffix, background in (
            ("", surface), ("/10 tint", blend(surface, fill, tint_alphas[0], False)),
            ("/15 tint", blend(surface, fill, tint_alphas[1], False)),
        )
    ]
    link_backgrounds = backgrounds + [
        (f"{name} with {label}/15 tint", blend(surface, color, .15, False))
        for name, surface in zip(("bg", "surface", "panel"), surfaces)
        for label, color in zip(("accent", "success", "warn"), FIXED_FILLS)
    ]
    ink = rgb(theme["accent_color"]) if theme.get("accent_color") else fill
    if not custom:
        ink = (90, 22, 51) if mode == "light" else PRODUCT_FILL
    endpoint = (0, 0, 0) if mode == "light" else (255, 255, 255)
    for step in range(101):
        candidate = blend(ink, endpoint, step / 100)
        if all(contrast(candidate, background) >= 4.5 for _, background in link_backgrounds):
            ink = candidate
            break
    pairs = []
    for name, background in (("secondary", fill), ("secondary-hover", hover), ("secondary-active", active)):
        pairs.append((f"on-secondary on {name}", contrast(foreground, background), 4.5))
        # Existing catalogue counters use text-on-secondary/80.
        counter = tuple(text * .8 + channel * .2 for text, channel in zip(foreground, background))
        pairs.append((f"on-secondary/80 on {name}", contrast(counter, background), 4.5))
    pairs.extend((f"secondary-ink on {name}", contrast(ink, background), 4.5) for name, background in link_backgrounds)
    pairs.extend((f"{label} on {name}", contrast(text, background), 4.5)
                 for label, text in zip(("ink", "muted"), BODY_TEXT[mode]) for name, background in backgrounds)
    pairs.extend((f"{label} on {name}", contrast(text, background), 4.5)
                 for label, text in zip(("accent-ink", "success-ink", "warn-ink", "danger"), FIXED_INKS[mode])
                 for name, background in backgrounds)
    pairs.extend((f"secondary boundary on {name}", contrast(ink, surface), 3) for name, surface in zip(("bg", "surface", "panel"), surfaces))
    return {"fill": fill, "foreground": foreground, "hover": hover, "active": active, "ink": ink, "tint_alphas": tint_alphas, "pairs": pairs}


def contrast_failures(theme):
    return [
        {"mode": mode, "pair": pair, "ratio": ratio, "minimum": minimum}
        for mode in SURFACES
        for pair, ratio, minimum in derive_palette(theme, mode)["pairs"]
        if ratio < minimum
    ]
