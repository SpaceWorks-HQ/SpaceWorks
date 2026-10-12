"""Explicit compatibility barrel for staff list and detail views."""

from .views_admin_event_list import EventListCreateView
from .views_admin_event_detail import (
    EVENT_ERROR_400,
    EVENT_ERROR_409,
    EVENT_SCOPED_ERRORS,
    EVENT_VALIDATION_ERROR_SCHEMA,
    _EventPagination,
    _RegistrationPagination,
    _visible_makerspace,
    _manageable_event,
    _manageable_registration,
    _annotate_registration_counts,
    _paginated_response,
    _validate_empty_action,
    EventDetailView,
    _EventActionView,
    EventPublishView,
    EventCancelView,
    EventCompleteView,
)
