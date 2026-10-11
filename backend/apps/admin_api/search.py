"""Bounded discovery within the existing staff list surfaces."""

from types import SimpleNamespace

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.admin_api.staff_list_scope import request_scope, visible_space
from apps.hardware_requests.exceptions import ErrorSerializer
from apps.makerspaces.platform import feature_enabled, module_enabled


class SearchThrottle(UserRateThrottle):
    scope = "staff_search"
    rate = "60/min"


class SearchInput(serializers.Serializer):
    makerspace_id = serializers.IntegerField(min_value=1, max_value=9223372036854775807)
    q = serializers.CharField(min_length=2, max_length=100, trim_whitespace=True)
    limit = serializers.IntegerField(min_value=1, max_value=10, default=5)


class SearchHit(serializers.Serializer):
    entity = serializers.ChoiceField(choices=["requests", "inventory", "members", "bookings", "events", "machines"])
    id = serializers.IntegerField()
    label = serializers.CharField()
    tab = serializers.CharField()
    query = serializers.DictField(child=serializers.CharField())


class SearchOutput(serializers.Serializer):
    results = SearchHit(many=True)


def search_hits(actor, space, term, limit):
    from apps.hardware_requests.queue_views import ScopedPiiSearchFilter
    from apps.inventory.models import InventoryProduct
    from apps.admin_api.inventory_filters import apply_inventory_list_filters
    from apps.inventory.search import apply_q
    from apps.machines import access
    from apps.machines.models import Machine
    from apps.makerspaces.models import MakerspaceMembership

    hits = []

    def add(entity, rows, label, tab=None, query=None):
        for row in rows.order_by("pk")[:limit]:
            hits.append({"entity": entity, "id": row.pk, "label": label(row), "tab": tab or entity,
                         "query": query(row) if query else {"q": term}})

    if rbac.can(actor, rbac.Action.VIEW_INVENTORY, space.pk) and module_enabled(space, "staff_admin"):
        rows = rbac.scope_by_action(actor, rbac.Action.VIEW_INVENTORY, InventoryProduct.objects.filter(makerspace=space, is_archived=False))
        add("inventory", apply_inventory_list_filters(rows, {"q": term, "archived": "false"}), lambda row: row.name, query=lambda row: {"id": str(row.pk)})

    if feature_enabled(space, "loans.enabled"):
        rows = request_scope(actor, space.pk)
        # Keep the queue's blind-index / dual-read behavior for encrypted requester
        # fields; never query ciphertext with icontains or decrypt an unscoped table.
        rows = ScopedPiiSearchFilter().filter_queryset(
            SimpleNamespace(query_params={"search": term}), rows,
            SimpleNamespace(kwargs={"makerspace_id": space.pk}),
        )
        add("requests", rows, lambda row: f"Request #{row.pk} · {row.requested_for}", query=lambda row: {"id": str(row.pk), "history": "true"})

    if rbac.can(actor, rbac.Action.MANAGE_MEMBERS, space.pk):
        rows = rbac.scope_by_action(actor, rbac.Action.MANAGE_MEMBERS, MakerspaceMembership.objects.filter(makerspace=space).select_related("user"))
        # Username is the existing unencrypted account identifier. Name/email
        # fuzzy discovery needs a separate global-PII indexing product decision.
        add("members", rows.filter(user__username__icontains=term), lambda row: row.user.username, query=lambda row: {"id": str(row.pk)})

    if rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, space.pk) and module_enabled(space, "bookings"):
        from apps.bookings.models import Booking
        rows = rbac.scope_by_action(actor, rbac.Action.MANAGE_BOOKINGS, Booking.objects.filter(space__makerspace=space).select_related("space"), field="space__makerspace_id")
        match = Q(space__name__icontains=term)
        if term.isdecimal() and len(term) <= 19 and int(term) <= 9223372036854775807:
            match |= Q(pk=int(term))
        add("bookings", rows.filter(match), lambda row: f"Booking #{row.pk} · {row.space.name}", query=lambda row: {"space": str(row.space_id), "booking": str(row.pk)})

    if rbac.can(actor, rbac.Action.MANAGE_EVENTS, space.pk) and module_enabled(space, "events"):
        from apps.events.models import Event
        rows = rbac.scope_by_action(actor, rbac.Action.MANAGE_EVENTS, Event.objects.filter(makerspace=space))
        add("events", apply_q(rows, term, label_field="title"), lambda row: row.title, query=lambda row: {"event": str(row.pk), "q": term})

    if module_enabled(space, "machines") and access.can_see_machines(actor, space.pk):
        rows = access.scope_machines_for_actor(actor, Machine.objects.filter(makerspace=space))
        add("machines", apply_q(rows, term), lambda row: row.name, query=lambda row: {"machine": str(row.pk)})
    return hits


class StaffSearchView(APIView):
    permission_classes = [IsActiveStaff]
    throttle_classes = [SearchThrottle]

    @extend_schema(tags=["Staff lists"], summary="Search authorized staff lists", parameters=[SearchInput], request=None,
                   description="At most limit hits per entity (default 5, maximum 10). Members match username; bookings match space name or booking ID. Disabled or unauthorized entity lists contribute no hits.",
                   responses={200: SearchOutput, **{code: ErrorSerializer for code in (400, 401, 403, 404, 429)}})
    def get(self, request):
        payload = SearchInput(data=request.query_params)
        payload.is_valid(raise_exception=True)
        values = payload.validated_data
        space = visible_space(request.user, values["makerspace_id"])
        return Response({"results": search_hits(request.user, space, values["q"], values["limit"])})
