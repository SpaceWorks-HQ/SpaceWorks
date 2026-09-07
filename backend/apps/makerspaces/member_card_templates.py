"""Card layout templates: selectors and dimensions only, never member values.

Stored per makerspace as JSON (`Makerspace.member_card_template`-less by design: the template
lives in `branding_config["member_card_template"]` so no schema change is needed and it
travels with the branding it belongs to). Presets are the two things a card printer wants:
one CR80 card, or an A4/Letter sheet of ten.
"""
from math import floor

from rest_framework.exceptions import ValidationError

CR80_WIDTH_MM = 85.6
CR80_HEIGHT_MM = 54.0
PAGE_SIZES_MM = {"cr80": (CR80_WIDTH_MM, CR80_HEIGHT_MM), "a4": (210.0, 297.0), "letter": (215.9, 279.4)}
FIELD_CHOICES = ("printed_name", "card_number", "makerspace", "issued_at", "membership_role", "certifications")
DEFAULT_TEMPLATE = {
    "version": 1,
    "page": "a4",
    "orientation": "portrait",
    "card_width_mm": CR80_WIDTH_MM,
    "card_height_mm": CR80_HEIGHT_MM,
    "margin_mm": 10.0,
    "gap_mm": 5.0,
    "front_fields": ["printed_name", "card_number", "makerspace"],
    "back_text": "",
    "include_photo": True,
    "include_qr": True,
    "name_font_size_pt": 12,
    "font_size_pt": 8,
    "crop_marks": True,
}
BRANDING_KEY = "member_card_template"


def normalize_template(value):
    template = dict(DEFAULT_TEMPLATE)
    template.update({k: v for k, v in (value or {}).items() if k in DEFAULT_TEMPLATE})
    errors = {}
    if template["page"] not in PAGE_SIZES_MM:
        errors["page"] = f"Choose one of {', '.join(PAGE_SIZES_MM)}."
    if template["orientation"] not in ("portrait", "landscape"):
        errors["orientation"] = "portrait or landscape."
    for key in ("card_width_mm", "card_height_mm", "margin_mm", "gap_mm"):
        try:
            template[key] = float(template[key])
        except (TypeError, ValueError):
            errors[key] = "A number of millimetres."
            continue
        if template[key] < 0 or template[key] > 400:
            errors[key] = "Between 0 and 400 mm."
    for key in ("name_font_size_pt", "font_size_pt"):
        try:
            template[key] = int(template[key])
        except (TypeError, ValueError):
            errors[key] = "A whole number of points."
            continue
        if not 5 <= template[key] <= 40:
            errors[key] = "Between 5 and 40 pt."
    fields = template["front_fields"]
    if not isinstance(fields, list) or not fields or any(f not in FIELD_CHOICES for f in fields):
        errors["front_fields"] = f"A non-empty list drawn from {', '.join(FIELD_CHOICES)}."
    if not isinstance(template["back_text"], str) or len(template["back_text"]) > 600:
        errors["back_text"] = "Up to 600 characters."
    template["include_photo"] = bool(template["include_photo"])
    template["include_qr"] = bool(template["include_qr"])
    template["crop_marks"] = bool(template["crop_marks"])
    if errors:
        raise ValidationError(errors)
    if template["page"] == "cr80":
        template["margin_mm"], template["gap_mm"] = 0.0, 0.0
        template["card_width_mm"], template["card_height_mm"] = CR80_WIDTH_MM, CR80_HEIGHT_MM
    return template


def page_layout(template):
    width, height = PAGE_SIZES_MM[template["page"]]
    if template["orientation"] == "landscape" and template["page"] != "cr80":
        width, height = height, width
    if template["page"] == "cr80":
        return width, height, 1, 1
    columns = max(1, floor((width - 2 * template["margin_mm"] + template["gap_mm"]) / (template["card_width_mm"] + template["gap_mm"])))
    rows = max(1, floor((height - 2 * template["margin_mm"] + template["gap_mm"]) / (template["card_height_mm"] + template["gap_mm"])))
    return width, height, columns, rows


def template_for(makerspace):
    return normalize_template((makerspace.branding_config or {}).get(BRANDING_KEY))


def save_template(makerspace, value):
    template = normalize_template(value)
    branding = dict(makerspace.branding_config or {})
    branding[BRANDING_KEY] = template
    makerspace.branding_config = branding
    makerspace.save(update_fields=["branding_config", "updated_at"])
    return template
