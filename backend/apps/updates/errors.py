from rest_framework.exceptions import APIException


class UpdateRefused(APIException):
    status_code = 400
    default_code = "update_refused"

    def __init__(self, reason, detail):
        super().__init__({"reason": reason, "detail": detail})
