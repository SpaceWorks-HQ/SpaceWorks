"""Events' member-facing surface, mounted under `/api/v1/member/`.

Separate from `urls_admin.py` (staff) and `urls_public.py` (the public catalogue) for one
reason that is easy to get wrong: this route has to be **withdrawn by an events
tombstone**. Declaring it in `apps/makerspaces/urls.py` -- where the rest of the
`member/` surface lives -- would leave it resolving, and advertised in the OpenAPI schema,
on a deployment that ships no events app at all. `config.urls.separable` splices this
urlconf in place instead, exactly as it does for the other two.
"""

from django.urls import path

from apps.events.views_checkin import EventCheckInQrView
from apps.events.views_member_events import (
    MemberCollaborativeEventListView,
    MemberCollaborativeEventRegistrationView,
)

urlpatterns = [
    path(
        'makerspaces/<int:makerspace_id>/collaborative-events/',
        MemberCollaborativeEventListView.as_view(),
        name='member-collaborative-events',
    ),
    path(
        'makerspaces/<int:makerspace_id>/collaborative-events/<int:pk>/register/',
        MemberCollaborativeEventRegistrationView.as_view(),
        name='member-collaborative-event-register',
    ),
    path(
        'makerspaces/<int:makerspace_id>/event-registrations/<int:pk>/qr',
        EventCheckInQrView.as_view(),
        name='member-event-checkin-qr',
    ),
]
