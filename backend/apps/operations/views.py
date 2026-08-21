import csv
from io import BytesIO, StringIO

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from openpyxl import Workbook
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff, IsActiveSuperAdmin, require_action
from apps.audit import services as audit
from apps.boxes.models import Box, QrCode, QrScanEvent
from apps.boxes.serializers import BoxSerializer, QrCodeSerializer
from apps.inventory.models import InventoryAsset, InventoryProduct
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace
from apps.operations import ledger, qr_zip, reports, services
from apps.operations.models import QrPrintBatch, StockTransfer, StocktakeSession
from apps.operations.serializers import (
    AssetGenerateResultSerializer,
    AssetGenerateSerializer,
    ContainerContentsSerializer,
    ContainerHistorySerializer,
    ContainerMoveSerializer,
    EmptySerializer,
    GenericObjectSerializer,
    HealthSerializer,
    LedgerResponseSerializer,
    QrPrintBatchCreateSerializer,
    QrPrintBatchDetailSerializer,
    QrPrintBatchItemCreateSerializer,
    QrPrintBatchItemResultSerializer,
    QrPrintBatchSerializer,
    ReadinessSerializer,
    StockTransferCreateSerializer,
    StockTransferSerializer,
    StocktakeCreateSerializer,
    StocktakeLineInputSerializer,
    StocktakeLineSerializer,
    StocktakeSerializer,
)
from apps.operations.views_dashboard import DashboardView
from apps.operations.views_containers import (
    ContainerContentsView,
    ContainerDetailView,
    ContainerHistoryView,
    ContainerListCreateView,
    ContainerMoveView,
)
from apps.operations.views_health import HealthView, ReadinessView
from apps.operations.views_ledger import (
    AggregateLedgerExportView,
    AggregateLedgerView,
    LedgerExportView,
    LedgerView,
    _ledger_payload,
)
from apps.operations.views_qr_batches import (
    AssetGenerateView,
    AssetQrView,
    QrPrintBatchDetailView,
    QrPrintBatchDownloadView,
    QrPrintBatchItemView,
    QrPrintBatchListCreateView,
)
from apps.operations.views_problem_reports import (
    ProblemReportResolveView,
    ProblemReportTriageView,
)
from apps.operations.views_org_reports import OrganizationAnalyticsView
from apps.operations.views_reports import (
    AccountabilityReportView,
    AggregateAnalyticsView,
    AggregateReportExportView,
    AnalyticsView,
    ReportExportView,
    _csv_response,
    _makerspace_for_inventory_view,
    _require_superadmin,
    _xlsx_cell,
    _xlsx_response,
    report_data,
    report_rows,
)
from apps.operations.views_stocktake import (
    StocktakeApplyAdjustmentsView,
    StocktakeApproveView,
    StocktakeCompleteView,
    StocktakeCountLineView,
    StocktakeDetailView,
    StocktakeListCreateView,
    StocktakeResolveScanView,
    _stocktake_for_action,
)
from apps.operations.views_transfers import StockTransferDetailView, StockTransferListCreateView
