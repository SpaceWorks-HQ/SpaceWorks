class InvalidTransition(Exception):
    pass


class RequesterBlocked(Exception):
    pass


class RequestValidationError(Exception):
    pass


class AnonymousRequestIdempotencyConflict(Exception):
    pass


class AnonymousRequestOutstandingLimit(Exception):
    pass


class ReturnValidationError(Exception):
    pass


class BoxValidationError(Exception):
    """Bad box input (unknown/inactive box code) - maps to 400."""


class BoxUnavailable(Exception):
    """Box is already out on another active loan - maps to 409."""


class EvidenceNotUploaded(Exception):
    pass
