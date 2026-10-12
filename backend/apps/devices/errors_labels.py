from rest_framework.exceptions import APIException


class LabelConflict(APIException):
    status_code = 409
    default_detail = "Label operation conflicts with its durable state."
    default_code = "label_conflict"


class LabelGone(APIException):
    status_code = 410
    default_detail = "The label batch is no longer available."
    default_code = "label_gone"
