"""The discoverable list for organizer-derived event authority.

Kept out of `views_admin.py`, which is already past this repo's ~300-line ceiling.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView

from apps.admin_api.permissions import IsActiveStaff
from apps.events.models import Event
from apps.events.organizer_authority import organizer_event_q
from apps.events.serializers_admin import (
    EventAdminSerializer,
    EventListResponseSerializer,
)
from apps.events.views_admin import (
    _EventPagination,
    _annotate_registration_counts,
    _paginated_response,
)


class OrganizedEventListView(APIView):
    """List the events this actor's organizations organize, across venues.

    Organizer authority is deliberately per-event and grants nothing over the venue, so an
    organizer at a venue their organization is not linked to cannot use the venue's event
    list -- which left the per-event endpoints reachable only by someone who already knew a
    database id. This is the discoverable surface for that authority: it lists exactly the
    events the organizer predicate matches and confers no venue authority whatsoever.
    """

    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Events'],
        summary='List events organized by the actor\'s organizations',
        request=None,
        responses={200: EventListResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        # Resolved as a SUBQUERY, not a join: an actor in two organizations that both
        # organize one event matches organizer_event_q twice, and duplicate joined rows
        # would double every Count in _annotate_registration_counts. distinct() cannot
        # undo duplication inside an aggregate, so the outer queryset carries no organizer
        # join at all.
        organized_ids = Event.objects.filter(
            organizer_event_q(request.user)
        ).values('pk')
        queryset = Event.objects.filter(pk__in=organized_ids).select_related('makerspace')
        queryset = (
            _annotate_registration_counts(queryset)
            .prefetch_related('organizers__organization')
            .order_by('starts_at', 'id')
        )
        paginator = _EventPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return _paginated_response(paginator, page, EventAdminSerializer)
