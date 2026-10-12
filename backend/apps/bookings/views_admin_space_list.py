from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings import services
from apps.bookings.models import BookableSpace
from apps.bookings.serializers_admin import BookableSpaceAdminSerializer, BookableSpaceListResponseSerializer, BookableSpaceWriteSerializer
from .views_admin_space_detail import (
    _visible_makerspace,
    _SpacePagination,
    _page_response,
    VALIDATED_ERROR_RESPONSES,
)
from apps.admin_api.list_options import LIST_PARAMETERS, order_list


class BookableSpaceListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='List bookable spaces in a makerspace',
        request=None,
        parameters=LIST_PARAMETERS,
        responses={200: BookableSpaceListResponseSerializer, **VALIDATED_ERROR_RESPONSES},
    )
    def get(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        queryset = rbac.scope_by_action(
            request.user,
            rbac.Action.MANAGE_BOOKINGS,
            BookableSpace.objects.select_related('makerspace').filter(
                makerspace=makerspace
            ),
            field='makerspace_id',
        ).order_by('name', 'id')
        if request.query_params.get("q"):
            queryset = queryset.filter(name__icontains=request.query_params["q"])
        queryset = order_list(queryset, request.query_params, {"name", "kind", "created_at"}, "name")
        paginator = _SpacePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return _page_response(paginator, page, BookableSpaceAdminSerializer)

    @extend_schema(
        tags=['Admin bookings'],
        summary='Create a bookable space',
        request=BookableSpaceWriteSerializer,
        responses={201: BookableSpaceAdminSerializer, **VALIDATED_ERROR_RESPONSES},
    )
    def post(self, request, makerspace_id, *args, **kwargs):
        makerspace = _visible_makerspace(request.user, makerspace_id)
        serializer = BookableSpaceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        space = services.create_space(
            makerspace=makerspace,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(
            BookableSpaceAdminSerializer(space).data,
            status=status.HTTP_201_CREATED,
        )

