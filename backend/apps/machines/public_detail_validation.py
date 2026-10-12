def validate_public_fields(value):
    from django.core.exceptions import ValidationError
    if (not isinstance(value, list) or any(field not in ("training", "queue_eta") for field in value)
            or len(value) != len(set(value))):
        raise ValidationError("Public fields may contain training and queue_eta only.")


