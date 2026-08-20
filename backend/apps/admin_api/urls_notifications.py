from django.urls import path

from apps.admin_api.views_email_logs import EmailLogListView, EmailLogRetryView
from apps.admin_api.views_email_templates import (
    EmailTemplateDetailView,
    EmailTemplateListView,
    EmailTemplatePreviewView,
    EmailTemplateResetView,
    MachineTypeEmailTemplateDetailView,
    MachineTypeEmailTemplateResetView,
)
from apps.admin_api.views_integration_health import IntegrationHealthView
from apps.admin_api.views_notification_destinations import (
    NotificationDestinationDetailView,
    NotificationDestinationListView,
)
from apps.admin_api.views_notification_recipients import NotificationRecipientsView
from apps.admin_api.views_notification_rules import NotificationRulesView
from apps.admin_api.views_recipient_rules import NotificationRecipientRulesView


urlpatterns = [
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
        "makerspace/<int:makerspace_id>/notification-recipient-rules",
        NotificationRecipientRulesView.as_view(),
        name="admin-notification-recipient-rules",
    ),
    path(
        "makerspace/<int:makerspace_id>/notification-destinations",
        NotificationDestinationListView.as_view(),
        name="admin-notification-destinations",
    ),
    path(
        "makerspace/<int:makerspace_id>/notification-destinations/<int:destination_id>",
        NotificationDestinationDetailView.as_view(),
        name="admin-notification-destination-detail",
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
        "makerspace/<int:makerspace_id>/email-templates/<str:stream>/<str:audience>/<str:key>/types/<int:machine_type_id>/reset",
        MachineTypeEmailTemplateResetView.as_view(),
        name="admin-machine-type-email-template-reset",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates/<str:stream>/<str:audience>/<str:key>/types/<int:machine_type_id>",
        MachineTypeEmailTemplateDetailView.as_view(),
        name="admin-machine-type-email-template-detail",
    ),
    path(
        "makerspace/<int:makerspace_id>/email-templates/<str:stream>/<str:audience>/<str:key>",
        EmailTemplateDetailView.as_view(),
        name="admin-email-template-detail",
    ),
]
