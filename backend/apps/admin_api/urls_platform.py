from django.urls import path

from apps.admin_api.views_modules import (
    ModuleGroupListView,
    ModuleInstallView,
    ModuleUninstallView,
)
from apps.admin_api.views_payment_settings import (
    MakerspacePaymentSettingsView,
    StripeConnectOnboardingView,
)
from apps.admin_api.views_platform import PlatformEmailSettingsView
from apps.admin_api.views_platform_payments import PlatformStripeConnectSettingsView
from apps.admin_api.views_platform_social import PlatformSocialAuthSettingsView
from apps.admin_api.views_platform_updates import (
    PlatformUpdateRequestView,
    PlatformUpdateSettingsView,
)
from apps.backup.views_archives import (
    BackupDownloadUrlView,
    DeploymentArchiveListCreateView,
    MakerspaceArchiveListCreateView,
)
from apps.backup.views_restore import (
    PlatformBackupSettingsView,
    RestoreDecisionView,
    RestoreOperationListCreateView,
    RestoreOperationView,
)
from apps.data_export.views import (
    DataExportDetailView,
    DataExportDownloadUrlView,
    DataExportListCreateView,
)
from apps.tenant_migration.views import (
    DeploymentIdentityView,
    DisclosureApprovalListCreateView,
    DisclosureApprovalRevokeView,
    DisclosureClosureView,
    MigrationExportDetailView,
    MigrationExportDownloadUrlView,
    MigrationExportListCreateView,
    MigrationPairingListCreateView,
    SourceArchiveView,
    SourceQuiesceView,
    SourceRecoverView,
    TargetAbortView,
    TargetActivateView,
    TenantImportDetailView,
    TenantImportIdentityDecisionsView,
    TenantImportListCreateView,
    TenantImportRunView,
    TenantImportVerificationView,
)

from .urls_utils import _separable


urlpatterns = [
    path(
        "platform/backup-settings",
        PlatformBackupSettingsView.as_view(),
        name="admin-platform-backup-settings",
    ),
    path(
        "platform/backups",
        DeploymentArchiveListCreateView.as_view(),
        name="admin-deployment-backups",
    ),
    path(
        "makerspace/<int:makerspace_id>/backups",
        MakerspaceArchiveListCreateView.as_view(),
        name="admin-makerspace-backups",
    ),
    path(
        "backups/<uuid:archive_id>/download-url",
        BackupDownloadUrlView.as_view(),
        name="admin-backup-download-url",
    ),
    path(
        "platform/restores",
        RestoreOperationListCreateView.as_view(),
        name="admin-restore-operations",
    ),
    path(
        "platform/restores/<uuid:restore_id>",
        RestoreOperationView.as_view(),
        name="admin-restore-operation",
    ),
    path(
        "platform/restores/<uuid:restore_id>/decision",
        RestoreDecisionView.as_view(),
        name="admin-restore-decision",
    ),
    path(
        "makerspace/<int:makerspace_id>/data-exports",
        DataExportListCreateView.as_view(),
        name="data-export-list-create",
    ),
    path(
        "makerspace/<int:makerspace_id>/data-exports/<uuid:job_id>",
        DataExportDetailView.as_view(),
        name="data-export-detail",
    ),
    path(
        "makerspace/<int:makerspace_id>/data-exports/<uuid:job_id>/download-url",
        DataExportDownloadUrlView.as_view(),
        name="data-export-download-url",
    ),
    *_separable(
        "tenant_migration",
        path("platform/tenant-migrations/deployment-identity", DeploymentIdentityView.as_view(), name="tenant-migration-deployment-identity"),
        path("platform/tenant-migrations/pairings", MigrationPairingListCreateView.as_view(), name="tenant-migration-pairings"),
        path("platform/tenant-migrations/imports", TenantImportListCreateView.as_view(), name="tenant-migration-imports"),
        path("platform/tenant-migrations/imports/<uuid:job_id>", TenantImportDetailView.as_view(), name="tenant-migration-import-detail"),
        path("platform/tenant-migrations/imports/<uuid:job_id>/identity-decisions", TenantImportIdentityDecisionsView.as_view(), name="tenant-migration-import-decisions"),
        path("platform/tenant-migrations/imports/<uuid:job_id>/run", TenantImportRunView.as_view(), name="tenant-migration-import-run"),
        path("platform/tenant-migrations/imports/<uuid:job_id>/verification", TenantImportVerificationView.as_view(), name="tenant-migration-import-verification"),
        path("platform/tenant-migrations/imports/<uuid:job_id>/pairings/<uuid:pairing_id>/activate", TargetActivateView.as_view(), name="tenant-migration-target-activate"),
        path("platform/tenant-migrations/imports/<uuid:job_id>/pairings/<uuid:pairing_id>/abort", TargetAbortView.as_view(), name="tenant-migration-target-abort"),
        path("makerspace/<int:makerspace_id>/tenant-migration/disclosure-closure", DisclosureClosureView.as_view(), name="tenant-migration-disclosure-closure"),
        path("makerspace/<int:makerspace_id>/tenant-migration/disclosure-approvals", DisclosureApprovalListCreateView.as_view(), name="tenant-migration-disclosure-approvals"),
        path("makerspace/<int:makerspace_id>/tenant-migration/disclosure-approvals/<uuid:approval_id>/revoke", DisclosureApprovalRevokeView.as_view(), name="tenant-migration-disclosure-revoke"),
        path("makerspace/<int:makerspace_id>/tenant-migration/exports", MigrationExportListCreateView.as_view(), name="tenant-migration-exports"),
        path("makerspace/<int:makerspace_id>/tenant-migration/exports/<uuid:job_id>", MigrationExportDetailView.as_view(), name="tenant-migration-export-detail"),
        path("makerspace/<int:makerspace_id>/tenant-migration/exports/<uuid:job_id>/download-url", MigrationExportDownloadUrlView.as_view(), name="tenant-migration-export-download-url"),
        path("makerspace/<int:makerspace_id>/tenant-migration/exports/<uuid:job_id>/quiesce", SourceQuiesceView.as_view(), name="tenant-migration-source-quiesce"),
        path("makerspace/<int:makerspace_id>/tenant-migration/pairings/<uuid:pairing_id>/archive-source", SourceArchiveView.as_view(), name="tenant-migration-source-archive"),
        path("makerspace/<int:makerspace_id>/tenant-migration/pairings/<uuid:pairing_id>/recover", SourceRecoverView.as_view(), name="tenant-migration-source-recover"),
    ),
    # Module install/uninstall. NOT wrapped in _separable: the registry is core, and a
    # console that could not list modules on a deployment with one app tombstoned would
    # be unable to show the operator what they had removed.
    path(
        "makerspace/<int:makerspace_id>/modules",
        ModuleGroupListView.as_view(),
        name="admin-module-groups",
    ),
    path(
        "makerspace/<int:makerspace_id>/modules/install",
        ModuleInstallView.as_view(),
        name="admin-module-install",
    ),
    path(
        "makerspace/<int:makerspace_id>/modules/uninstall",
        ModuleUninstallView.as_view(),
        name="admin-module-uninstall",
    ),
    *_separable(
        "updates",
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
    ),
    *_separable(
        "payments",
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
    ),
]


settings_urlpatterns = [
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
]
