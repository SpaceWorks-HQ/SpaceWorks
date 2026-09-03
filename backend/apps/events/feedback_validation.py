from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.forms_schema.validation import validate_answers, validate_form_schema


FEEDBACK_QUESTION_TYPES = frozenset(
    {
        "short_text",
        "paragraph",
        "dropdown",
        "multi_choice",
        "single_choice",
        "yes_no",
        "number",
    }
)


def validate_feedback_schema(value):
    canonical = validate_form_schema(value) or []
    unsupported = sorted(
        {question["type"] for question in canonical} - FEEDBACK_QUESTION_TYPES
    )
    if unsupported:
        raise DjangoValidationError(
            f"Unsupported feedback question type: {', '.join(unsupported)}."
        )
    return canonical


def validate_feedback_answers(schema, raw_answers):
    try:
        snapshot = validate_answers(schema, raw_answers)
    except serializers.ValidationError as exc:
        detail = exc.detail
        if "custom_answers" in detail:
            raise serializers.ValidationError(
                {"answers": detail["custom_answers"]}
            ) from exc
        raise
    return snapshot or {"version": 1, "answers": []}
