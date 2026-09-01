from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.events.serializers_public import PublicEventSerializer
from apps.inventory import public_image_storage
from apps.organizations.models import Organization


class PublicOrganizationSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    catalogue_links = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = (
            "slug",
            "name",
            "description",
            "website",
            "logo_url",
            "catalogue_links",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, obj):
        return public_image_storage.public_url(obj.logo_key) or None

    @extend_schema_field(
        serializers.DictField(child=serializers.CharField())
    )
    def get_catalogue_links(self, obj):
        return {
            "events": f"/api/v1/public/organizations/{obj.slug}/events/",
        }


class OrganizationEventHostSerializer(serializers.Serializer):
    slug = serializers.SlugField(read_only=True)
    name = serializers.CharField(read_only=True)
    logo_url = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_logo_url(self, obj):
        return public_image_storage.public_url(obj.logo_key) or None


class PublicOrganizationEventSerializer(PublicEventSerializer):
    host = OrganizationEventHostSerializer(source="makerspace", read_only=True)


class PublicOrganizationEventListSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = PublicOrganizationEventSerializer(many=True)
