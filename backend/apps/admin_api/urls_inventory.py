from django.urls import path

from apps.admin_api import views


urlpatterns = [
    path(
        "makerspace/<int:makerspace_id>/inventory",
        views.InventoryListCreateView.as_view(),
        name="admin-inventory",
    ),
    path(
        "makerspace/<int:makerspace_id>/inventory/export",
        views.InventoryExportView.as_view(),
        name="admin-inventory-export",
    ),
    path("inventory/<int:pk>", views.InventoryDetailView.as_view(), name="admin-inventory-detail"),
    path("inventory/<int:pk>/qr-history", views.ProductQrHistoryView.as_view(), name="admin-inventory-qr-history"),
    path("inventory/<int:product_pk>/assets", views.InventoryAssetListView.as_view(), name="admin-inventory-assets"),
    path("assets/<int:pk>", views.InventoryAssetDetailView.as_view(), name="admin-inventory-asset-detail"),
    path("assets/<int:pk>/fix-status", views.InventoryAssetStatusActionView.as_view(), name="admin-inventory-asset-fix-status"),
    path("assets/<int:pk>/qr-history", views.AssetQrHistoryView.as_view(), name="admin-inventory-asset-qr-history"),
    path(
        "inventory/<int:pk>/image",
        views.InventoryProductImageView.as_view(),
        name="admin-inventory-image",
    ),
    path(
        "inventory/needs-fix",
        views.NeedsFixShelfListView.as_view(),
        name="admin-needs-fix-shelf",
    ),
    path(
        "inventory/<int:pk>/needs-fix",
        views.NeedsFixActionView.as_view(),
        name="admin-needs-fix-action",
    ),
    path(
        "inventory/<int:pk>/lending-history",
        views.InventoryLendingHistoryView.as_view(),
        name="admin-inventory-lending-history",
    ),
    path(
        "inventory/<int:pk>/adjust-quantity",
        views.InventoryQuantityAdjustmentView.as_view(),
        name="admin-inventory-adjust-quantity",
    ),
    path(
        "makerspace/<int:makerspace_id>/categories",
        views.CategoryListCreateView.as_view(),
        name="admin-categories",
    ),
    path(
        "categories/<int:pk>",
        views.CategoryDetailView.as_view(),
        name="admin-category-detail",
    ),
    path(
        "makerspace/<int:makerspace_id>/inventory/import/preview",
        views.BulkImportPreviewView.as_view(),
        name="inventory-import-preview",
    ),
    path(
        "makerspace/<int:makerspace_id>/inventory/import/apply",
        views.BulkImportApplyView.as_view(),
        name="inventory-import-apply",
    ),
    path(
        "makerspace/<int:makerspace_id>/inventory/import/jobs",
        views.BulkImportJobListCreateView.as_view(),
        name="inventory-import-jobs",
    ),
    path(
        "makerspace/<int:makerspace_id>/inventory/import/jobs/<int:job_id>",
        views.BulkImportJobDetailView.as_view(),
        name="inventory-import-job-detail",
    ),
]
