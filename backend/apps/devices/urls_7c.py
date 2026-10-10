from django.urls import path

from apps.devices.views_labels import LabelCommandListView, LabelContentView, LabelResultView

label_urlpatterns = [
    path("admin/qr-print-batches/<int:pk>/label-commands", LabelCommandListView.as_view(),
         name="admin-label-command-list"),
    path("device/label-commands/<uuid:pk>/content", LabelContentView.as_view(),
         name="device-label-command-content"),
    path("device/label-commands/<uuid:pk>/result", LabelResultView.as_view(),
         name="device-label-command-result"),
]
