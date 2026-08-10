"""Avatar and project image upload/attach/clear for the caller's own profile.

Mirrors `events.views_admin_image` step for step, including the order of the checks: the
prefix test runs before anything touches storage, because it is what stops one makerspace
attaching another's object.

One endpoint set serves both the avatar and a project image, discriminated by an optional
`project_id`. Two near-identical triples would have been two places to forget the
key-collision check.
"""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.admin_api.serializers_inventory import (
    PublicImageAttachRequestSerializer,
    PublicImageUploadRequestSerializer,
    PublicImageUploadResponseSerializer,
)
from apps.evidence.responses import storage_unavailable_response
from apps.evidence.storage import StorageUnavailable
from apps.inventory import public_image_storage
from apps.makerspaces import profile_images, profile_services
from apps.makerspaces.profile_serializers import ProfileReadSerializer
from apps.makerspaces.profile_views import MemberProfileBaseView

IMAGE_KIND = profile_images.IMAGE_KIND


class ProfileImageUploadRequestSerializer(PublicImageUploadRequestSerializer):
    project_id = serializers.IntegerField(required=False)


class ProfileImageAttachRequestSerializer(PublicImageAttachRequestSerializer):
    project_id = serializers.IntegerField(required=False)


class MemberProfileImageView(MemberProfileBaseView):
    def _project(self, profile, project_id):
        if project_id is None:
            return None
        project = profile.projects.filter(pk=project_id).first()
        if project is None:
            # 400 rather than 404: the profile exists and is the caller's, so this is a
            # bad field in their payload, not a missing resource.
            raise ValidationError({"project_id": "Unknown project."})
        return project

    @extend_schema(
        tags=["Member profile"],
        summary="Create a profile image upload URL",
        request=ProfileImageUploadRequestSerializer,
        responses={
            201: PublicImageUploadResponseSerializer,
            400: OpenApiResponse(description="Invalid image upload request."),
            403: OpenApiResponse(description="An active membership is required."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def post(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        serializer = ProfileImageUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        content_type = serializer.validated_data["content_type"]
        ext = public_image_storage.ext_for(
            content_type, serializer.validated_data["filename"]
        )
        object_key = public_image_storage.build_object_key(
            IMAGE_KIND, membership.makerspace_id, ext
        )
        try:
            upload = public_image_storage.presigned_upload(object_key, content_type)
        except StorageUnavailable:
            return storage_unavailable_response()
        return Response(
            PublicImageUploadResponseSerializer({"object_key": object_key, **upload}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        tags=["Member profile"],
        summary="Attach an uploaded image to the profile or one of its projects",
        request=ProfileImageAttachRequestSerializer,
        responses={
            200: ProfileReadSerializer,
            400: OpenApiResponse(description="Invalid image object key or size."),
            403: OpenApiResponse(description="An active membership is required."),
            503: OpenApiResponse(description="Public image storage is unavailable."),
        },
    )
    def put(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        serializer = ProfileImageAttachRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        object_key = serializer.validated_data["object_key"]
        profile = profile_services.profile_for(membership)
        project = self._project(profile, serializer.validated_data.get("project_id"))

        if not object_key.startswith(f"{IMAGE_KIND}/{membership.makerspace_id}/"):
            raise ValidationError(
                {"object_key": "Image object key is outside this makerspace."}
            )
        if not public_image_storage.is_safe_object_key(object_key):
            raise ValidationError({"object_key": "Invalid image object key."})
        if public_image_storage.public_image_key_in_use(
            membership.makerspace_id,
            object_key,
            profile_id=None if project else profile.pk,
            project_id=project.pk if project else None,
        ):
            raise ValidationError({"object_key": "This image is already in use."})
        try:
            result = public_image_storage.finalize_upload(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if result.status != "ok":
            if result.status in {"empty", "too_large"}:
                _discard(object_key)
            raise ValidationError(
                {"object_key": public_image_storage.finalize_error_message(result)}
            )
        try:
            is_valid_image = public_image_storage.sniff_is_valid_image(object_key)
        except StorageUnavailable:
            return storage_unavailable_response()
        if not is_valid_image:
            _discard(object_key)
            raise ValidationError({"object_key": "Uploaded file is not a valid image."})
        if project is not None:
            profile_images.set_project_image(profile, project, object_key)
        else:
            profile_images.set_avatar(profile, object_key)
        return Response(ProfileReadSerializer(profile_services.read_profile(membership)).data)

    @extend_schema(
        tags=["Member profile"],
        summary="Clear a profile or project image",
        responses={
            200: ProfileReadSerializer,
            400: OpenApiResponse(description="Unknown project."),
            403: OpenApiResponse(description="An active membership is required."),
        },
    )
    def delete(self, request, makerspace_id):
        membership = self.membership(request, makerspace_id)
        profile = profile_services.profile_for(membership)
        raw_project_id = request.query_params.get("project_id")
        project = None
        if raw_project_id is not None:
            # A malformed id must NOT degrade to "no project": that branch clears the
            # avatar, so `?project_id=abc` would destroy a different image than the one
            # the caller named. Present-but-unparseable is a 400.
            if not raw_project_id.isdigit():
                raise ValidationError({"project_id": "Invalid project id."})
            project = self._project(profile, int(raw_project_id))
        if project is not None:
            profile_images.clear_project_image(profile, project)
        elif profile.avatar_key:
            profile_images.set_avatar(profile, "")
        return Response(ProfileReadSerializer(profile_services.read_profile(membership)).data)


def _discard(object_key):
    public_image_storage.delete_object(object_key)
    public_image_storage.delete_object(public_image_storage.staging_key(object_key))
