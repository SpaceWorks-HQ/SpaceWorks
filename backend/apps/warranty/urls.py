"""Warranty's staff API, relocated out of `admin_api` (plan B5/B6, phase 10).

Mounted at the same `/api/v1/admin/` prefix `admin_api` uses, and the route names are
unchanged, so every path and every `reverse()` behaves exactly as before -- the move is
about ownership, not about the API surface. Two things depend on that: the committed
OpenAPI snapshot, and `makerspaces.origin_scope_routes`, which keys the browser
origin->tenant guard by bare `url_name`.

Deliberately **no** `app_name`: `admin_api/urls.py` declares none, so these names are
unnamespaced today. Adding one would silently break `reverse("admin-warranty-documents")`
at every call site rather than failing loudly at import.
"""

from django.urls import path

from apps.warranty.views import (
    AssetWarrantyView,
    MachineWarrantyView,
    MakerspaceWarrantyReportView,
)
from apps.warranty.views_documents import (
    WarrantyDocumentCreateView,
    WarrantyDocumentDeleteView,
    WarrantyDocumentPresignView,
    WarrantyDocumentUrlView,
)

urlpatterns = [
    # Hosted on the asset and machine paths because a warranty has no standalone
    # identity -- it is always about one of its three hosts.
    path("assets/<int:pk>/warranty", AssetWarrantyView.as_view(), name="admin-asset-warranty"),
    path("machines/<int:pk>/warranty", MachineWarrantyView.as_view(), name="admin-machine-warranty"),
    path(
        "warranty/<int:pk>/documents/presign",
        WarrantyDocumentPresignView.as_view(),
        name="admin-warranty-document-presign",
    ),
    path(
        "warranty/<int:pk>/documents",
        WarrantyDocumentCreateView.as_view(),
        name="admin-warranty-documents",
    ),
    path(
        "warranty/documents/<int:pk>/url",
        WarrantyDocumentUrlView.as_view(),
        name="admin-warranty-document-url",
    ),
    path(
        "warranty/documents/<int:pk>",
        WarrantyDocumentDeleteView.as_view(),
        name="admin-warranty-document-detail",
    ),
    path(
        "makerspace/<int:makerspace_id>/warranties",
        MakerspaceWarrantyReportView.as_view(),
        name="admin-makerspace-warranties",
    ),
]
