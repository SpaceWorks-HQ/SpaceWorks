from math import floor

from rest_framework import serializers


DEFAULT_BADGE_TEMPLATE = {
    "version": 1,
    "paper_size": "A4",
    "orientation": "portrait",
    "page_width_mm": None,
    "page_height_mm": None,
    "card_width_mm": 90.0,
    "card_height_mm": 55.0,
    "margin_mm": 10.0,
    "gap_mm": 5.0,
    "template": "standard",
    "fields": ["name", "event_title", "date_time", "location", "registration_number"],
    "font_size_pt": 9,
    "name_font_size_pt": 15,
    "text_align": "left",
    "include_qr": True,
}
SAFE_FIELDS = frozenset({
    "name", "event_title", "date_time", "location", "registration_number",
})
SENSITIVE_FIELDS = frozenset({"email", "phone"})
MAX_BADGES = 200
MAX_PAGES = 50
MAX_TEXT_LENGTH = 500


def _page_dimensions(template):
    sizes = {"A4": (210.0, 297.0), "LETTER": (215.9, 279.4)}
    if template["paper_size"] == "custom":
        width, height = template["page_width_mm"], template["page_height_mm"]
    else:
        width, height = sizes[template["paper_size"]]
    if template["orientation"] == "landscape":
        width, height = height, width
    return width, height


def _custom_ids(event):
    return {str(question["id"]) for question in (event.custom_form or [])}


def normalize_badge_template(value, event):
    if value in (None, {}):
        value = DEFAULT_BADGE_TEMPLATE
    if not isinstance(value, dict):
        raise serializers.ValidationError({"badge_template": "Expected an object."})
    unknown = set(value) - set(DEFAULT_BADGE_TEMPLATE)
    if unknown:
        raise serializers.ValidationError({key: "Unknown template field." for key in unknown})
    template = {**DEFAULT_BADGE_TEMPLATE, **value}
    if template["version"] != 1:
        raise serializers.ValidationError({"version": "Only badge template version 1 is supported."})
    if template["paper_size"] not in {"A4", "LETTER", "custom"}:
        raise serializers.ValidationError({"paper_size": "Use A4, LETTER, or custom."})
    if template["orientation"] not in {"portrait", "landscape"}:
        raise serializers.ValidationError({"orientation": "Use portrait or landscape."})
    if template["template"] != "standard":
        raise serializers.ValidationError({"template": "Unknown badge template."})
    if template["text_align"] not in {"left", "center"}:
        raise serializers.ValidationError({"text_align": "Use left or center."})
    if type(template["include_qr"]) is not bool:
        raise serializers.ValidationError({"include_qr": "Expected a boolean."})
    numeric_bounds = {
        "card_width_mm": (40, 150), "card_height_mm": (30, 120),
        "margin_mm": (0, 40), "gap_mm": (0, 30),
        "font_size_pt": (6, 18), "name_font_size_pt": (8, 28),
    }
    if template["paper_size"] == "custom":
        numeric_bounds.update({"page_width_mm": (100, 500), "page_height_mm": (100, 500)})
    for field, (minimum, maximum) in numeric_bounds.items():
        value = template[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise serializers.ValidationError({field: "Expected a number."})
        if not minimum <= value <= maximum:
            raise serializers.ValidationError({field: f"Must be between {minimum} and {maximum}."})
        template[field] = float(value)
    fields = template["fields"]
    if not isinstance(fields, list) or not fields or len(fields) > 12:
        raise serializers.ValidationError({"fields": "Choose between 1 and 12 fields."})
    if len(fields) != len(set(fields)) or any(not isinstance(item, str) for item in fields):
        raise serializers.ValidationError({"fields": "Field selectors must be unique strings."})
    custom_ids = _custom_ids(event)
    invalid = [item for item in fields if (
        item not in SAFE_FIELDS | SENSITIVE_FIELDS
        and not (item.startswith("custom:") and item[7:] in custom_ids)
    )]
    if invalid:
        raise serializers.ValidationError({"fields": f"Unknown selectors: {', '.join(invalid)}."})
    width, height = _page_dimensions(template)
    usable_width = width - 2 * template["margin_mm"]
    usable_height = height - 2 * template["margin_mm"]
    columns = floor((usable_width + template["gap_mm"]) / (
        template["card_width_mm"] + template["gap_mm"]
    ))
    rows = floor((usable_height + template["gap_mm"]) / (
        template["card_height_mm"] + template["gap_mm"]
    ))
    if columns < 1 or rows < 1:
        raise serializers.ValidationError({"badge_template": "No badge fits on the configured page."})
    template["fields"] = fields
    return template


def page_layout(template):
    width, height = _page_dimensions(template)
    columns = floor((width - 2 * template["margin_mm"] + template["gap_mm"]) / (
        template["card_width_mm"] + template["gap_mm"]
    ))
    rows = floor((height - 2 * template["margin_mm"] + template["gap_mm"]) / (
        template["card_height_mm"] + template["gap_mm"]
    ))
    return width, height, columns, rows
