from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import rbac
from apps.admin_api.permissions import IsActiveStaff
from apps.bookings.serializers_admin import (
    BookableSpaceAdminSerializer,
    BookableSpaceListResponseSerializer,
    BookableSpaceWriteSerializer,
    EmptyActionSerializer,
    SpaceImageFinalizeRequestSerializer,
    SpaceImagePresignRequestSerializer,
    SpaceImagePresignResponseSerializer,
)
from apps.bookings import services, services_images, storage
from apps.bookings.models import BookableSpace
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.hardware_requests.view_helpers import (
    ERROR_400,
    ERROR_403,
    ERROR_404,
    ERROR_409,
    ERROR_503,
)
from apps.makerspaces.guards import require_module
from apps.makerspaces.models import Makerspace


SCOPED_ERROR_RESPONSES = {403: ERROR_403, 404: ERROR_404}
VALIDATED_ERROR_RESPONSES = {400: ERROR_400, **SCOPED_ERROR_RESPONSES}
IMAGE_ERROR_RESPONSES = {**VALIDATED_ERROR_RESPONSES, 503: ERROR_503}


class _SpacePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _visible_makerspace(actor, makerspace_id):
    makerspace = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_BOOKINGS,
            Makerspace.objects.all(),
            field='id',
        ),
        pk=makerspace_id,
    )
    require_module(makerspace, 'bookings')
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, makerspace.pk):
        raise PermissionDenied()
    return makerspace


def manageable_space(actor, pk):
    space = get_object_or_404(
        rbac.scope_by_visibility_or_action(
            actor,
            rbac.Action.MANAGE_BOOKINGS,
            BookableSpace.objects.select_related('makerspace'),
            field='makerspace_id',
        ),
        pk=pk,
    )
    require_module(space.makerspace, 'bookings')
    if not rbac.can(actor, rbac.Action.MANAGE_BOOKINGS, space.makerspace_id):
        raise PermissionDenied()
    return space


def _page_response(paginator, page, serializer):
    return Response(
        {
            'count': paginator.page.paginator.count,
            'next': paginator.get_next_link(),
            'previous': paginator.get_previous_link(),
            'results': serializer(page, many=True).data,
        }
    )


def _require_active(space):
    if not space.is_active:
        raise ValidationError(
            {'space': 'Inactive spaces cannot have images changed.'}
        )


class BookableSpaceListCreateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='List bookable spaces in a makerspace',
        request=None,
        responses={200: BookableSpaceListResponseSerializer, **SCOPED_ERROR_RESPONSES},
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


class BookableSpaceDetailView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Retrieve a bookable space',
        request=None,
        responses={200: BookableSpaceAdminSerializer, **SCOPED_ERROR_RESPONSES},
    )
    def get(self, request, pk, *args, **kwargs):
        return Response(
            BookableSpaceAdminSerializer(manageable_space(request.user, pk)).data
        )

    @extend_schema(
        tags=['Admin bookings'],
        summary='Update a bookable space',
        request=BookableSpaceWriteSerializer,
        responses={
            200: BookableSpaceAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def patch(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        serializer = BookableSpaceWriteSerializer(
            space,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        space = services.update_space(
            space,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(BookableSpaceAdminSerializer(space).data)


class BookableSpaceDeactivateView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Deactivate a bookable space',
        request=EmptyActionSerializer,
        responses={
            200: BookableSpaceAdminSerializer,
            **VALIDATED_ERROR_RESPONSES,
            409: ERROR_409,
        },
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        serializer = EmptyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        space = services.deactivate_space(space, actor=request.user)
        return Response(BookableSpaceAdminSerializer(space).data)


class BookableSpaceImagePresignView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Create a space image upload URL',
        request=SpaceImagePresignRequestSerializer,
        responses={201: SpaceImagePresignResponseSerializer, **IMAGE_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        _require_active(space)
        serializer = SpaceImagePresignRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data['content_type']
        ext = storage.ext_for(content_type, serializer.validated_data['filename'])
        object_key = storage.build_object_key(space.makerspace_id, space.pk, ext)
        try:
            upload = storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        data = {'object_key': object_key, 'upload': upload}
        return Response(
            SpaceImagePresignResponseSerializer(data).data,
            status=status.HTTP_201_CREATED,
        )


def _cleanup_new_upload(space, object_key):
    services_images.cleanup_unattached_space_image(
        space,
        object_key=object_key,
        storage=storage,
    )


class BookableSpaceImageFinalizeView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Finalize and attach a space image',
        request=SpaceImageFinalizeRequestSerializer,
        responses={200: BookableSpaceAdminSerializer, **IMAGE_ERROR_RESPONSES},
    )
    def post(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        _require_active(space)
        serializer = SpaceImageFinalizeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data['object_key']
        services.validate_space_image_key(space, object_key)
        if storage.public_image_key_in_use(space.makerspace_id, object_key):
            raise ValidationError({'object_key': 'This image is already in use.'})
        try:
            result = storage.finalize_upload(object_key)
        except StorageUnavailable:
            _cleanup_new_upload(space, object_key)
            return storage_unavailable_response()
        if result.status != 'ok':
            _cleanup_new_upload(space, object_key)
            raise ValidationError(
                {'object_key': storage.finalize_error_message(result)}
            )
        try:
            valid_image = storage.sniff_is_valid_image(object_key)
        except StorageUnavailable:
            _cleanup_new_upload(space, object_key)
            return storage_unavailable_response()
        if not valid_image:
            _cleanup_new_upload(space, object_key)
            raise ValidationError({'object_key': 'Uploaded file is not a valid image.'})
        try:
            space = services.set_space_image(
                space,
                actor=request.user,
                object_key=object_key,
                size_bytes=result.size,
            )
        except Exception:
            _cleanup_new_upload(space, object_key)
            raise
        return Response(BookableSpaceAdminSerializer(space).data)


class BookableSpaceImageDeleteView(APIView):
    permission_classes = [IsActiveStaff]

    @extend_schema(
        tags=['Admin bookings'],
        summary='Delete a space image',
        request=None,
        responses={204: None, **IMAGE_ERROR_RESPONSES},
    )
    def delete(self, request, pk, *args, **kwargs):
        space = manageable_space(request.user, pk)
        services.remove_space_image(space, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
