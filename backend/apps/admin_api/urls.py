from django.urls import path

from apps.admin_api import api_client_views, views
from apps.admin_api.views_email_templates import (
    EmailTemplateDetailView,
    EmailTemplateListView,
    EmailTemplatePreviewView,
    EmailTemplateResetView,
)
from apps.admin_api.views_email_logs import EmailLogListView, EmailLogRetryView
from apps.admin_api.views_integration_health import IntegrationHealthView
from apps.admin_api.views_bookable_spaces import (
    BookableSpaceDeactivateView,
    BookableSpaceDetailView,
    BookableSpaceImageDeleteView,
    BookableSpaceImageFinalizeView,
    BookableSpaceImagePresignView,
    BookableSpaceListCreateView,
)
from apps.admin_api.views_bookings import (
    BookingApproveView,
    BookingCancelView,
    BookingCompleteView,
    BookingNoShowView,
    BookingRejectView,
    SpaceBookingListView,
)
from apps.admin_api.views_booking_rules import BookableSpaceBookingRulesView
from apps.admin_api.views_hosting import MakerspaceProvisionSubdomainView
from apps.admin_api.views_machine_documents import (
    MachineDocumentDeleteView,
    MachineDocumentPresignView,
    MachineDocumentsView,
    MachineDocumentUrlView,
)
from apps.admin_api.views_machine_candidates import MachineOperatorCandidatesView
from apps.admin_api.views_machine_consumables import (
    MachineConsumableCandidatesView,
    MachineConsumableDetailView,
    MachineConsumablesView,
    MachineConsumptionLogView,
)
from apps.admin_api.views_machine_image import MachineImageView
from apps.admin_api.views_machine_publicity import MachinePublicityView
from apps.admin_api.views_machine_operators import (
    MachineOperatorDetailView,
    MachineOperatorsView,
)
from apps.admin_api.views_machine_types import (
    MachineTypeDetailView,
    MachineTypeListCreateView,
)
from apps.admin_api.views_machine_type_pricing import (
    MachineTypePricingDetailView,
    MachineTypePricingListView,
)
from apps.admin_api.views_machines import MachineDetailView, MachineListCreateView
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
from apps.admin_api.views_payments import PaymentMarkOfflineView, PaymentWaiveView
from apps.admin_api.views_payment_settings import (
    MakerspacePaymentSettingsView,
    StripeConnectOnboardingView,
)
from apps.admin_api.views_platform_payments import PlatformStripeConnectSettingsView
from apps.admin_api.views_machine_service_printer import (
    MachineServicePrinterPoolAdjustmentView,
    MachineServicePrinterPoolDetailView,
    MachineServicePrinterPoolListCreateView,
    MachineServiceTypedManualUsageView,
)
from apps.admin_api.views_machine_service_files import (
    MachineServiceFileDeleteView,
    MachineServiceFileFinalizeView,
    MachineServiceFilePresignView,
    MachineServiceFileUrlView,
)
from apps.machines.service_reports_views import (
    MakerspaceMachineServiceReportView,
    SuperadminMachineServiceReportView,
)
from apps.admin_api.views_machines_actions import (
    MachineErrorLogView,
    MachineRetireView,
    MachineSetStatusView,
    MachineUnretireView,
    MachineUsageView,
)
from apps.admin_api.views_notification_recipients import NotificationRecipientsView
from apps.admin_api.views_notification_rules import NotificationRulesView
from apps.admin_api.views_platform import PlatformEmailSettingsView
from apps.admin_api.views_platform_social import PlatformSocialAuthSettingsView
from apps.admin_api.views_platform_updates import (
    PlatformUpdateRequestView,
    PlatformUpdateSettingsView,
)
from apps.admin_api.views_subdomain_requests import SubdomainRequestListCreateView
from apps.makerspaces.models import MakerspaceMembership
from apps.admin_api.views_memberships import (
    MembershipListCreateView,
    MembershipRoleAssignView,
)
from apps.admin_api.views_member_memberships import (
    AdminInvitationView, AdminMembershipRequestListView, AdminMembershipRevokeM2View,
    AdminMembershipRoleM2View, AdminMembershipRosterView, AdminRequestApproveView,
    AdminRequestRevokeView, AdminWaiverView,
)
from apps.admin_api.views_member_capabilities import (
    AdminMembershipCapabilitiesView,
    AdminMembershipUnverifyView,
    AdminMembershipVerifyView,
)
from apps.admin_api.views_roles import CapabilityCatalogView, RoleDetailView, RoleListCreateView

urlpatterns = [
    path(
        "platform/update-settings",
        PlatformUpdateSettingsView.as_view(),
        name="admin-platform-update-settings",
    ),
    path(
        "platform/update-settings/update-now",
        PlatformUpdateRequestView.as_view(),
        name="admin-platform-update-now",
    ),
    path(
        "platform/payment-settings",
        PlatformStripeConnectSettingsView.as_view(),
        name="admin-platform-payment-settings",
    ),
    path(
        "makerspace/<int:makerspace_id>/payment-settings",
        MakerspacePaymentSettingsView.as_view(),
        name="admin-makerspace-payment-settings",
    ),
    path(
        "makerspace/<int:makerspace_id>/payment-settings/connect/onboard",
        StripeConnectOnboardingView.as_view(),
        name="admin-makerspace-payment-connect-onboard",
    ),
    path("memberships", AdminMembershipRosterView.as_view(), name="admin-memberships-roster"),
    path("membership-requests", AdminMembershipRequestListView.as_view(), name="admin-membership-requests"),
    path("makerspace/<int:makerspace_id>/membership-invitations", AdminInvitationView.as_view(), name="admin-membership-invitations"),
    path("membership-requests/<int:pk>/approve", AdminRequestApproveView.as_view(), name="admin-membership-request-approve"),
    path("membership-requests/<int:pk>/revoke", AdminRequestRevokeView.as_view(), name="admin-membership-request-revoke"),
    path("memberships/<int:pk>/revoke", AdminMembershipRevokeM2View.as_view(), name="admin-membership-revoke-m2"),
    path("memberships/<int:pk>/role", AdminMembershipRoleM2View.as_view(), name="admin-membership-role-m2"),
    path("memberships/<int:pk>/capabilities", AdminMembershipCapabilitiesView.as_view(), name="admin-membership-capabilities"),
    path("memberships/<int:pk>/verify", AdminMembershipVerifyView.as_view(), name="admin-membership-verify"),
    path("memberships/<int:pk>/unverify", AdminMembershipUnverifyView.as_view(), name="admin-membership-unverify"),
    path("makerspaces/<int:makerspace_id>/waiver", AdminWaiverView.as_view(), name="admin-makerspace-waiver"),
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
    path("machine-service/payments/<int:pk>/mark-offline", PaymentMarkOfflineView.as_view(), name="admin-machine-service-payment-mark-offline"),
    path("machine-service/payments/<int:pk>/waive", PaymentWaiveView.as_view(), name="admin-machine-service-payment-waive"),
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
    path(
        "makerspaces/<int:makerspace_id>/memberships",
        MembershipListCreateView.as_view(),
        name="admin-membership-list-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/memberships/<int:membership_id>/role",
        MembershipRoleAssignView.as_view(),
        name="admin-membership-role-assign",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles/capabilities",
        CapabilityCatalogView.as_view(),
        name="admin-role-capabilities",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles",
        RoleListCreateView.as_view(),
        name="admin-role-list-create",
    ),
    path(
        "makerspaces/<int:makerspace_id>/roles/<int:role_id>",
        RoleDetailView.as_view(),
        name="admin-role-detail",
    ),
    path(
        'makerspaces/<int:makerspace_id>/spaces/',
        BookableSpaceListCreateView.as_view(),
        name='admin-bookable-space-list-create',
    ),
    path(
        'spaces/<int:pk>/',
        BookableSpaceDetailView.as_view(),
        name='admin-bookable-space-detail',
    ),
    path(
        'spaces/<int:pk>/deactivate/',
        BookableSpaceDeactivateView.as_view(),
        name='admin-bookable-space-deactivate',
    ),
    path(
        'spaces/<int:pk>/image/presign/',
        BookableSpaceImagePresignView.as_view(),
        name='admin-bookable-space-image-presign',
    ),
    path(
        'spaces/<int:pk>/image/finalize/',
        BookableSpaceImageFinalizeView.as_view(),
        name='admin-bookable-space-image-finalize',
    ),
    path(
        'spaces/<int:pk>/image/',
        BookableSpaceImageDeleteView.as_view(),
        name='admin-bookable-space-image-delete',
    ),
    path(
        'spaces/<int:pk>/bookings/',
        SpaceBookingListView.as_view(),
        name='admin-space-booking-list',
    ),
    path(
        'spaces/<int:pk>/booking-rules/',
        BookableSpaceBookingRulesView.as_view(),
        name='admin-bookable-space-booking-rules',
    ),
    path(
        'bookings/<int:pk>/approve/',
        BookingApproveView.as_view(),
        name='admin-booking-approve',
    ),
    path(
        'bookings/<int:pk>/reject/',
        BookingRejectView.as_view(),
        name='admin-booking-reject',
    ),
    path(
        'bookings/<int:pk>/cancel/',
        BookingCancelView.as_view(),
        name='admin-booking-cancel',
    ),
    path(
        'bookings/<int:pk>/complete/',
        BookingCompleteView.as_view(),
        name='admin-booking-complete',
    ),
    path(
        'bookings/<int:pk>/no-show/',
        BookingNoShowView.as_view(),
        name='admin-booking-no-show',
    ),
    path(
        'makerspace/<int:makerspace_id>/machines',
        MachineListCreateView.as_view(),
        name='admin-machines',
    ),
    path(
        'makerspace/<int:makerspace_id>/machine-types',
        MachineTypeListCreateView.as_view(),
        name='admin-machine-types',
    ),
    path(
        'makerspace/<int:makerspace_id>/machine-types/<int:pk>',
        MachineTypeDetailView.as_view(),
        name='admin-machine-type-detail',
    ),
    path(
        'makerspace/<int:makerspace_id>/machine-type-pricing',
        MachineTypePricingListView.as_view(),
        name='admin-machine-type-pricing',
    ),
    path(
        'makerspace/<int:makerspace_id>/machine-type-pricing/<int:machine_type_id>',
        MachineTypePricingDetailView.as_view(),
        name='admin-machine-type-pricing-detail',
    ),
    path(
        'machines/<int:pk>',
        MachineDetailView.as_view(),
        name='admin-machine-detail',
    ),
    path(
        'machines/<int:pk>/image',
        MachineImageView.as_view(),
        name='admin-machine-image',
    ),
    path(
        'machines/<int:pk>/publicity',
        MachinePublicityView.as_view(),
        name='admin-machine-publicity',
    ),
    path(
        'machines/<int:pk>/set-status',
        MachineSetStatusView.as_view(),
        name='admin-machine-set-status',
    ),
    path(
        'machines/<int:pk>/retire',
        MachineRetireView.as_view(),
        name='admin-machine-retire',
    ),
    path(
        'machines/<int:pk>/unretire',
        MachineUnretireView.as_view(),
        name='admin-machine-unretire',
    ),
    path(
        'machines/<int:pk>/usage',
        MachineUsageView.as_view(),
        name='admin-machine-usage',
    ),
    path(
        'machines/<int:pk>/consumables',
        MachineConsumablesView.as_view(),
        name='admin-machine-consumables',
    ),
    path(
        'machines/<int:pk>/consumables/<int:cid>',
        MachineConsumableDetailView.as_view(),
        name='admin-machine-consumable-detail',
    ),
    path(
        'machines/<int:pk>/consumables/<int:cid>/log',
        MachineConsumptionLogView.as_view(),
        name='admin-machine-consumption-log',
    ),
    path(
        'machines/<int:pk>/consumable-candidates',
        MachineConsumableCandidatesView.as_view(),
        name='admin-machine-consumable-candidates',
    ),
    path(
        'machines/<int:pk>/operators',
        MachineOperatorsView.as_view(),
        name='admin-machine-operators',
    ),
    path(
        'machines/<int:pk>/operator-candidates',
        MachineOperatorCandidatesView.as_view(),
        name='admin-machine-operator-candidates',
    ),
    path(
        'machines/<int:pk>/operators/<int:user_pk>',
        MachineOperatorDetailView.as_view(),
        name='admin-machine-operator-detail',
    ),
    path(
        'machines/<int:pk>/documents/presign',
        MachineDocumentPresignView.as_view(),
        name='admin-machine-document-presign',
    ),
    path(
        'machines/<int:pk>/documents',
        MachineDocumentsView.as_view(),
        name='admin-machine-documents',
    ),
    path(
        'machines/documents/<int:pk>/url',
        MachineDocumentUrlView.as_view(),
        name='admin-machine-document-url',
    ),
    path(
        'machines/documents/<int:pk>',
        MachineDocumentDeleteView.as_view(),
        name='admin-machine-document-detail',
    ),
    path(
        'machines/<int:pk>/error-logs',
        MachineErrorLogView.as_view(),
        name='admin-machine-error-logs',
    ),
    path(
        "platform/email-settings",
        PlatformEmailSettingsView.as_view(),
        name="admin-platform-email-settings",
    ),
    path(
        "platform/social-auth-settings",
        PlatformSocialAuthSettingsView.as_view(),
        name="admin-platform-social-auth-settings",
    ),
    path("makerspaces", views.MakerspaceListCreateView.as_view(), name="admin-makerspaces"),
    path("makerspaces/<int:pk>", views.MakerspaceDetailView.as_view(), name="admin-makerspace"),
    path(
        "makerspace/<int:makerspace_id>/provision-subdomain",
        MakerspaceProvisionSubdomainView.as_view(),
        name="admin-makerspace-provision-subdomain",
    ),
    path(
        "makerspace/<int:makerspace_id>/subdomain-request",
        SubdomainRequestListCreateView.as_view(),
        name="admin-makerspace-subdomain-request",
    ),
    path(
        "makerspace/<int:makerspace_id>/verify-domain",
        views.MakerspaceVerifyDomainView.as_view(),
        name="makerspace-verify-domain",
    ),
    path(
        "makerspace/<int:makerspace_id>/return-policy",
        views.ReturnPolicyView.as_view(),
        name="admin-return-policy",
    ),
    path(
        "makerspace/<int:makerspace_id>/logo",
        views.MakerspaceLogoImageView.as_view(),
        name="admin-makerspace-logo",
    ),
    path(
        "makerspace/<int:makerspace_id>/cover",
        views.MakerspaceCoverImageView.as_view(),
        name="admin-makerspace-cover",
    ),
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
    path(
        "makerspace/<int:makerspace_id>/api-clients",
        api_client_views.ApiClientListCreateView.as_view(),
        name="admin-api-clients",
    ),
    path(
        "makerspace/<int:makerspace_id>/api-settings",
        api_client_views.ApiIntegrationSettingsView.as_view(),
        name="admin-api-settings",
    ),
    path(
        "makerspace/<int:makerspace_id>/notification-recipients",
        NotificationRecipientsView.as_view(),
        name="admin-notification-recipients",
    ),
    path(
        "makerspace/<int:makerspace_id>/notification-rules",
        NotificationRulesView.as_view(),
        name="admin-notification-rules",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates",
        EmailTemplateListView.as_view(),
        name="admin-email-templates",
    ),
    path(
        "makerspace/<int:makerspace_id>/integration-health",
        IntegrationHealthView.as_view(),
        name="makerspace-integration-health",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-logs",
        EmailLogListView.as_view(),
        name="admin-email-logs",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-logs/<int:pk>/retry",
        EmailLogRetryView.as_view(),
        name="admin-email-log-retry",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates/preview",
        EmailTemplatePreviewView.as_view(),
        name="admin-email-template-preview",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates/<str:stream>/<str:audience>/<str:key>/reset",
        EmailTemplateResetView.as_view(),
        name="admin-email-template-reset",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates/<str:stream>/<str:audience>/<str:key>",
        EmailTemplateDetailView.as_view(),
        name="admin-email-template-detail",
    ),
    path(
        "api-clients/<int:pk>",
        api_client_views.ApiClientDetailView.as_view(),
        name="admin-api-client",
    ),
    path(
        "api-clients/<int:pk>/rotate-secret",
        api_client_views.ApiClientRotateSecretView.as_view(),
        name="admin-api-client-rotate-secret",
    ),
    path(
        "api-key-requests",
        api_client_views.ApiKeyRequestListCreateView.as_view(),
        name="admin-api-key-requests",
    ),
    path(
        "users/space-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.SPACE_MANAGER},
        name="admin-users-space-managers",
    ),
    path(
        "users/inventory-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.INVENTORY_MANAGER},
        name="admin-users-inventory-managers",
    ),
    path(
        "users/guest-admins",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.GUEST_ADMIN},
        name="admin-users-guest-admins",
    ),
    path(
        "users/print-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.PRINT_MANAGER},
        name="admin-users-print-managers",
    ),
    path(
        "users/machine-managers",
        views.StaffListCreateView.as_view(),
        {"role": MakerspaceMembership.Role.MACHINE_MANAGER},
        name="admin-users-machine-managers",
    ),
    path(
        "memberships/<int:pk>",
        views.MembershipRevokeView.as_view(),
        name="admin-membership-revoke",
    ),
    path("users/<int:pk>/restrict", views.RestrictUserView.as_view(), name="user-restrict"),
    path(
        "users/<int:pk>/reset-password",
        views.ResetUserPasswordView.as_view(),
        name="admin-user-reset-password",
    ),
    path(
        "users/<int:pk>/restore-access",
        views.RestoreUserAccessView.as_view(),
        name="user-restore-access",
    ),
    path("audit-logs", views.AuditLogListView.as_view(), name="admin-audit-logs"),
]
