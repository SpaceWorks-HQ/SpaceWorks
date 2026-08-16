from drf_spectacular.utils import OpenApiResponse


AUTH_ERRORS = {
    401: OpenApiResponse(description="Authentication is required."),
    403: OpenApiResponse(description="The authenticated actor is not authorized."),
}

VALIDATION_ERROR = OpenApiResponse(description="The request is invalid for the current lifecycle state.")
NOT_FOUND = OpenApiResponse(description="The requested resource does not exist in the actor's scope.")
