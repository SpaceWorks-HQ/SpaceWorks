from django.urls import path

from apps.admin_api.views_machine_service import (
    MachineServiceAcceptView,
    MachineServiceCollectView,
    MachineServiceCompleteView,
    MachineServiceFailView,
    MachineServiceRejectView,
    MachineServiceRequestDetailView,
    MachineServiceRequestListCreateView,
    MachineServiceReprintView,
    MachineServiceStartView,
)
from apps.admin_api.views_machine_service_files import (
    MachineServiceFileDeleteView,
    MachineServiceFileFinalizeView,
    MachineServiceFilePresignView,
    MachineServiceFileUrlView,
)
from apps.admin_api.views_machine_service_printer import (
    MachineServicePrinterPoolAdjustmentView,
    MachineServicePrinterPoolDetailView,
    MachineServicePrinterPoolListCreateView,
    MachineServiceTypedManualUsageView,
)
from apps.admin_api.views_payments import PaymentMarkOfflineView, PaymentWaiveView
from apps.machines.service_reports_views import (
    MakerspaceMachineServiceReportView,
    SuperadminMachineServiceReportView,
)

from .urls_utils import _separable


urlpatterns = [
    path("makerspace/<int:makerspace_id>/machine-service-report", MakerspaceMachineServiceReportView.as_view(), name="admin-makerspace-machine-service-report"),
    path("machine-service-report", SuperadminMachineServiceReportView.as_view(), name="admin-machine-service-report"),
    path(
        "makerspaces/<int:makerspace_id>/machine-service/requests",
        MachineServiceRequestListCreateView.as_view(),
        name="admin-machine-service-request-list-create",
    ),
    path(
        "machine-service/requests/<int:pk>",
        MachineServiceRequestDetailView.as_view(),
        name="admin-machine-service-request-detail",
    ),
    path(
        "machine-service/requests/<int:pk>/accept",
        MachineServiceAcceptView.as_view(),
        name="admin-machine-service-request-accept",
    ),
    path(
        "machine-service/requests/<int:pk>/reject",
        MachineServiceRejectView.as_view(),
        name="admin-machine-service-request-reject",
    ),
    path(
        "machine-service/requests/<int:pk>/start",
        MachineServiceStartView.as_view(),
        name="admin-machine-service-request-start",
    ),
    path(
        "machine-service/requests/<int:pk>/complete",
        MachineServiceCompleteView.as_view(),
        name="admin-machine-service-request-complete",
    ),
    path(
        "machine-service/requests/<int:pk>/fail",
        MachineServiceFailView.as_view(),
        name="admin-machine-service-request-fail",
    ),
    path(
        "machine-service/requests/<int:pk>/collect",
        MachineServiceCollectView.as_view(),
        name="admin-machine-service-request-collect",
    ),
    *_separable(
        "payments",
        path("machine-service/payments/<int:pk>/mark-offline", PaymentMarkOfflineView.as_view(), name="admin-machine-service-payment-mark-offline"),
        path("machine-service/payments/<int:pk>/waive", PaymentWaiveView.as_view(), name="admin-machine-service-payment-waive"),
    ),
    path(
        "machine-service/requests/<int:pk>/reprint",
        MachineServiceReprintView.as_view(),
        name="admin-machine-service-request-reprint",
    ),
    path(
        "makerspaces/<int:makerspace_id>/machine-service/consumable-pools",
        MachineServicePrinterPoolListCreateView.as_view(),
        name="admin-machine-service-printer-pools",
    ),
    path(
        "machine-service/consumable-pools/<int:pk>",
        MachineServicePrinterPoolDetailView.as_view(),
        name="admin-machine-service-printer-pool-detail",
    ),
    path(
        "machine-service/consumable-pools/<int:pk>/adjustments",
        MachineServicePrinterPoolAdjustmentView.as_view(),
        name="admin-machine-service-printer-pool-adjustments",
    ),
    path(
        "makerspaces/<int:makerspace_id>/machine-service/typed-manual-usage",
        MachineServiceTypedManualUsageView.as_view(),
        name="admin-machine-service-printer-typed-manual-usage",
    ),
    path(
        "machine-service/requests/<int:pk>/files/presign",
        MachineServiceFilePresignView.as_view(),
        name="admin-machine-service-file-presign",
    ),
    path(
        "machine-service/requests/<int:pk>/files/finalize",
        MachineServiceFileFinalizeView.as_view(),
        name="admin-machine-service-file-finalize",
    ),
    path(
        "machine-service/files/<int:pk>/url",
        MachineServiceFileUrlView.as_view(),
        name="admin-machine-service-file-url",
    ),
    path(
        "machine-service/files/<int:pk>",
        MachineServiceFileDeleteView.as_view(),
        name="admin-machine-service-file-detail",
    ),
]
