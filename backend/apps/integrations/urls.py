from django.urls import path

from apps.integrations import views
from apps.integrations.views_push import PushDeviceDetailView, PushDeviceListCreateView
from .delivery_views import DeliveryLogListView, DeliveryLogRetryView, DeliveryTestView
from .suppression_views import SuppressionDeleteView, SuppressionListView

from .bounce_webhooks import BounceWebhookView
from .views_timing import TimingPolicyView

urlpatterns = [
    path("makerspace/<int:makerspace_id>/bounce-webhook", BounceWebhookView.as_view(), name="email-bounce-webhook"),
    path("makerspace/<int:makerspace_id>/timing-policy", TimingPolicyView.as_view(), name="notification-timing-policy"),
    path("makerspace/<int:makerspace_id>/delivery-logs", DeliveryLogListView.as_view(), name="delivery-log-list"),
    path("makerspace/<int:makerspace_id>/delivery-logs/<str:kind>/<int:pk>/retry", DeliveryLogRetryView.as_view(), name="delivery-log-retry"),
    path("makerspace/<int:makerspace_id>/delivery-test", DeliveryTestView.as_view(), name="delivery-test"),
    path("makerspace/<int:makerspace_id>/email-suppressions", SuppressionListView.as_view(), name="email-suppression-list"),
    path("makerspace/<int:makerspace_id>/email-suppressions/<int:pk>", SuppressionDeleteView.as_view(), name="email-suppression-delete"),
    path("push/devices", PushDeviceListCreateView.as_view(), name="push-device-list-create"),
    path("push/devices/<int:device_id>", PushDeviceDetailView.as_view(), name="push-device-detail"),
    path("telegram/webhook", views.TelegramWebhookView.as_view(), name="telegram-webhook"),
    path("telegram/test-alert", views.TelegramTestAlertView.as_view(), name="telegram-test-alert"),
]
