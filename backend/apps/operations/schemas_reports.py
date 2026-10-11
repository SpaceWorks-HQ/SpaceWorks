from drf_spectacular.utils import PolymorphicProxySerializer

from apps.operations.serializers import AnalyticsSummarySerializer
from apps.operations.serializers_reports import (
    ActiveLoansReportSerializer,
    DamagedLostReportSerializer,
    DamagedMissingReportSerializer,
    MostLentReportSerializer,
    QrScansReportSerializer,
    RecentlyAddedReportSerializer,
    ReturnsReportSerializer,
    TakenItemsReportSerializer,
    TopBorrowersReportSerializer,
    BookingUtilizationReportSerializer,
    EventAttendanceReportSerializer,
    FabLabHealthReportSerializer,
    MachineUsageReportSerializer,
    MaintenanceActivityReportSerializer,
    MemberActivityReportSerializer,
    PaymentReconciliationReportSerializer,
)
from apps.operations.serializers_report_catalog import GenericAnalyticsReportSerializer
from apps.operations.serializers_reports_payments import PaymentCashBookSerializer
from apps.operations.serializers_reports_membership import MemberRetentionReportSerializer, MembershipRevenueReportSerializer

ANALYTICS_REPORT_RESPONSE = PolymorphicProxySerializer(
    component_name="AnalyticsReportResponse",
    serializers=[
        AnalyticsSummarySerializer,
        TakenItemsReportSerializer,
        ActiveLoansReportSerializer,
        ReturnsReportSerializer,
        DamagedMissingReportSerializer,
        DamagedLostReportSerializer,
        QrScansReportSerializer,
        MostLentReportSerializer,
        TopBorrowersReportSerializer,
        RecentlyAddedReportSerializer,
        MachineUsageReportSerializer,
        EventAttendanceReportSerializer,
        BookingUtilizationReportSerializer,
        MaintenanceActivityReportSerializer,
        MemberActivityReportSerializer,
        FabLabHealthReportSerializer,
        PaymentReconciliationReportSerializer,
        PaymentCashBookSerializer,
        GenericAnalyticsReportSerializer,
        MemberRetentionReportSerializer,
        MembershipRevenueReportSerializer,
    ],
    resource_type_field_name=None,
)
