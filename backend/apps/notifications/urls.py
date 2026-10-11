from django.urls import path

from apps.notifications.views import (
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationMarkReadView,
    NotificationUnreadCountView,
)

app_name = "notifications"

from .views_inbox import InboxListView, InboxReadAllView, InboxReadView, InboxUnreadView
from .views_preferences import MemberPreferenceView, OneClickUnsubscribeView

from .views_broadcasts import BroadcastCreateView, AnnouncementFeedView

urlpatterns = [
    path("broadcasts/<int:makerspace_id>", BroadcastCreateView.as_view(), name="broadcast-create"),
    path("announcements/<int:makerspace_id>", AnnouncementFeedView.as_view(), name="announcement-feed"),
    path("inbox/<int:makerspace_id>", InboxListView.as_view(), name="inbox-list"),
    path("inbox/<int:makerspace_id>/unread-count", InboxUnreadView.as_view(), name="inbox-count"),
    path("inbox/<int:makerspace_id>/read-all", InboxReadAllView.as_view(), name="inbox-read-all"),
    path("inbox/<int:makerspace_id>/<int:pk>/read", InboxReadView.as_view(), name="inbox-read"),
    path("preferences/<int:makerspace_id>", MemberPreferenceView.as_view(), name="member-preferences"),
    path("unsubscribe/<str:token>", OneClickUnsubscribeView.as_view(), name="one-click-unsubscribe"),
    path(
        "makerspace/<int:makerspace_id>",
        NotificationListView.as_view(),
        name="notifications-list",
    ),
    path(
        "makerspace/<int:makerspace_id>/unread-count",
        NotificationUnreadCountView.as_view(),
        name="notifications-unread-count",
    ),
    path(
        "makerspace/<int:makerspace_id>/read-all",
        NotificationMarkAllReadView.as_view(),
        name="notifications-read-all",
    ),
    path(
        "makerspace/<int:makerspace_id>/<int:pk>/read",
        NotificationMarkReadView.as_view(),
        name="notifications-read",
    ),
]
