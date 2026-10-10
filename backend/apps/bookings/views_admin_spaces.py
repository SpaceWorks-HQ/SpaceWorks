"""Explicit compatibility barrel for staff list and detail views."""

from .views_admin_space_list import BookableSpaceListCreateView
from .views_admin_space_detail import (
    SCOPED_ERROR_RESPONSES,
    VALIDATED_ERROR_RESPONSES,
    IMAGE_ERROR_RESPONSES,
    _SpacePagination,
    _visible_makerspace,
    manageable_space,
    _page_response,
    _require_active,
    BookableSpaceDetailView,
    BookableSpaceDeactivateView,
    BookableSpaceImagePresignView,
    _cleanup_new_upload,
    BookableSpaceImageFinalizeView,
    BookableSpaceImageDeleteView,
)
