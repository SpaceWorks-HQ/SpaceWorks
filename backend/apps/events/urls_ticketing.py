from django.urls import path
from .views_invites import EventInviteListView, EventInviteRevokeView
from .views_ticketing import EventTicketListView, EventPromoListView, EventPromoRevokeView, EventCategoryListView

urlpatterns = [
    path("events/<int:pk>/invites/", EventInviteListView.as_view(), name="admin-event-invites"),
    path("event-invites/<int:pk>/revoke/", EventInviteRevokeView.as_view(), name="admin-event-invite-revoke"),
    path("events/<int:pk>/ticket-types/", EventTicketListView.as_view(), name="admin-event-tickets"),
    path("events/<int:pk>/promo-codes/", EventPromoListView.as_view(), name="admin-event-promos"),
    path("event-promos/<int:pk>/revoke/", EventPromoRevokeView.as_view(), name="admin-event-promo-revoke"),
    path("makerspaces/<int:makerspace_id>/event-categories/", EventCategoryListView.as_view(), name="admin-event-categories"),
]
