"""Events' staff API, relocated out of `admin_api` (plan B5/B6, phase 13).

Separate from `urls_public.py`, which carries the member-facing event list and
registration under `/api/v1/public/`; both are withdrawn by the same tombstone.

Mounted at `admin_api`'s own `/api/v1/admin/` prefix with unchanged paths and route
names, so `origin_scope_routes` (keyed by bare `url_name`), the OpenAPI snapshot and
every `reverse()` are unaffected. No `app_name`, matching `admin_api`.
"""

from django.urls import path

from apps.events.views_admin import (
    EventCancelView,
    EventEligibleMemberListView,
    EventCompleteView,
    EventDetailView,
    EventListCreateView,
    EventPublishView,
    EventRegistrationApproveView,
    EventRegistrationListView,
    EventRegistrationMarkAttendedView,
    EventRegistrationPromoteView,
    EventRegistrationRejectView,
)
from apps.events.views_admin_organized import OrganizedEventListView
from apps.events.views_admin_image import EventImageView
from apps.events.views_checkin import EventCheckInResolveView
from apps.events.views_feedback_admin import (
    EventCertificateDownloadView,
    EventCertificateReissueView,
    EventCertificateRevokeView,
    EventFeedbackResponseListView,
    EventFeedbackSurveyCloseView,
    EventFeedbackSurveyOpenView,
    EventFeedbackSurveyView,
    EventRegistrationCorrectAttendanceView,
)
from apps.events.views_collaborators import (
    EventCollaborationInboxView,
    EventCollaborationRemoveView,
    EventCollaborationRespondView,
    EventCollaboratorListView,
)

urlpatterns = [
    path(
        'makerspaces/<int:makerspace_id>/events/',
        EventListCreateView.as_view(),
        name='admin-event-list-create',
    ),
    path(
        'events/<int:pk>/',
        EventDetailView.as_view(),
        name='admin-event-detail',
    ),
    path(
        'events/<int:pk>/publish/',
        EventPublishView.as_view(),
        name='admin-event-publish',
    ),
    path(
        'events/<int:pk>/cancel/',
        EventCancelView.as_view(),
        name='admin-event-cancel',
    ),
    path(
        'events/<int:pk>/complete/',
        EventCompleteView.as_view(),
        name='admin-event-complete',
    ),
    path(
        'events/<int:pk>/image',
        EventImageView.as_view(),
        name='admin-event-image',
    ),
    path(
        'events/<int:pk>/registrations/',
        EventRegistrationListView.as_view(),
        name='admin-event-registration-list',
    ),
    path(
        'events/<int:pk>/feedback-survey/',
        EventFeedbackSurveyView.as_view(),
        name='admin-event-feedback-survey',
    ),
    path(
        'events/<int:pk>/feedback-survey/open/',
        EventFeedbackSurveyOpenView.as_view(),
        name='admin-event-feedback-survey-open',
    ),
    path(
        'events/<int:pk>/feedback-survey/close/',
        EventFeedbackSurveyCloseView.as_view(),
        name='admin-event-feedback-survey-close',
    ),
    path(
        'events/<int:pk>/feedback-responses/',
        EventFeedbackResponseListView.as_view(),
        name='admin-event-feedback-responses',
    ),
    path(
        'events/<int:pk>/collaborators/',
        EventCollaboratorListView.as_view(),
        name='admin-event-collaborators',
    ),
    path(
        'event-collaborations/<int:pk>/remove/',
        EventCollaborationRemoveView.as_view(),
        name='admin-event-collaboration-remove',
    ),
    path(
        'makerspaces/<int:makerspace_id>/event-collaborations/',
        EventCollaborationInboxView.as_view(),
        name='admin-event-collaboration-inbox',
    ),
    path(
        'event-collaborations/<int:pk>/respond/',
        EventCollaborationRespondView.as_view(),
        name='admin-event-collaboration-respond',
    ),
    # Keep the kwarg named `pk`: origin scope resolves MODEL_LOOKUPS from
    # kwargs.get('pk'), so another name would deny every custom-domain request.
    path(
        'events/<int:pk>/check-in/resolve/',
        EventCheckInResolveView.as_view(),
        name='admin-event-check-in-resolve',
    ),
    path(
        'events/<int:pk>/eligible-members/',
        EventEligibleMemberListView.as_view(),
        name='admin-event-eligible-members',
    ),
    path(
        'event-registrations/<int:pk>/mark-attended/',
        EventRegistrationMarkAttendedView.as_view(),
        name='admin-event-registration-mark-attended',
    ),
    path(
        'event-registrations/<int:pk>/correct-attendance/',
        EventRegistrationCorrectAttendanceView.as_view(),
        name='admin-event-registration-correct-attendance',
    ),
    path(
        'event-certificates/<int:pk>/download/',
        EventCertificateDownloadView.as_view(),
        name='admin-event-certificate-download',
    ),
    path(
        'event-certificates/<int:pk>/revoke/',
        EventCertificateRevokeView.as_view(),
        name='admin-event-certificate-revoke',
    ),
    path(
        'event-certificates/<int:pk>/reissue/',
        EventCertificateReissueView.as_view(),
        name='admin-event-certificate-reissue',
    ),
    path(
        'event-registrations/<int:pk>/approve/',
        EventRegistrationApproveView.as_view(),
        name='admin-event-registration-approve',
    ),
    path(
        'event-registrations/<int:pk>/reject/',
        EventRegistrationRejectView.as_view(),
        name='admin-event-registration-reject',
    ),
    path(
        'event-registrations/<int:pk>/promote/',
        EventRegistrationPromoteView.as_view(),
        name='admin-event-registration-promote',
    ),
    path(
        'organized-events/',
        OrganizedEventListView.as_view(),
        name='admin-organized-event-list',
    ),
]
