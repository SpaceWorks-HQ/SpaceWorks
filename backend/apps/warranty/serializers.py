from django.utils import timezone
from rest_framework import serializers

from apps.warranty.models import Warranty, WarrantyDocument
from apps.warranty.status import STATUS_CHOICES, warranty_status


class WarrantyDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = WarrantyDocument
        fields = [
            "id",
            "original_filename",
            "content_type",
            "size_bytes",
            "created_at",
        ]
        read_only_fields = fields


class WarrantySerializer(serializers.ModelSerializer):
    host_kind = serializers.SerializerMethodField()
    host_id = serializers.SerializerMethodField()
    host_label = serializers.SerializerMethodField()
    asset_id = serializers.SerializerMethodField()
    asset_tag = serializers.SerializerMethodField()
    serial_number = serializers.SerializerMethodField()
    machine_id = serializers.SerializerMethodField()
    machine_name = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    documents = WarrantyDocumentSerializer(many=True, read_only=True)

    class Meta:
        model = Warranty
        fields = [
            "id",
            "host_kind",
            "host_id",
            "host_label",
            "asset_id",
            "asset_tag",
            "serial_number",
            "machine_id",
            "machine_name",
            "purchased_on",
            "warranty_expires_on",
            "vendor_name",
            "vendor_contact",
            "status",
            "documents",
        ]
        read_only_fields = fields

    def get_host_kind(self, obj) -> str:
        if obj.machine_id:
            return "machine"
        if obj.asset_id:
            return "asset"
        return "machine"

    def get_host_id(self, obj) -> int:
        return obj.machine_id or obj.asset_id

    def get_host_label(self, obj) -> str:
        if obj.machine_id:
            return obj.machine.name
        if obj.asset_id:
            return obj.asset.asset_tag
        return obj.machine.name

    def get_asset_id(self, obj) -> int | None:
        return obj.asset_id

    def get_asset_tag(self, obj) -> str | None:
        return obj.asset.asset_tag if obj.asset_id else None

    def get_serial_number(self, obj) -> str | None:
        return obj.asset.serial_number if obj.asset_id else None

    def get_machine_id(self, obj) -> int | None:
        return obj.machine_id

    def get_machine_name(self, obj) -> str | None:
        return obj.machine.name if obj.machine_id else None

    def get_status(self, obj) -> str:
        return warranty_status(obj, timezone.localdate())


class WarrantyUpsertSerializer(serializers.Serializer):
    purchased_on = serializers.DateField(allow_null=True, required=False)
    warranty_expires_on = serializers.DateField(allow_null=True, required=False)
    vendor_name = serializers.CharField(max_length=200, allow_blank=True, required=False)
    vendor_contact = serializers.CharField(max_length=200, allow_blank=True, required=False)


class WarrantyDocumentPresignSerializer(serializers.Serializer):
    filename = serializers.CharField(allow_blank=False, max_length=255)
    content_type = serializers.CharField(allow_blank=False, max_length=100)


class WarrantyDocumentFinalizeSerializer(serializers.Serializer):
    object_key = serializers.CharField(allow_blank=False, max_length=300)
    original_filename = serializers.CharField(allow_blank=False, max_length=255)


class WarrantyDocumentUploadResponseSerializer(serializers.Serializer):
    object_key = serializers.CharField()
    upload = serializers.DictField()


class WarrantyDocumentUrlSerializer(serializers.Serializer):
    url = serializers.URLField()


class WarrantyReportRowSerializer(serializers.Serializer):
    host_kind = serializers.CharField()
    host_id = serializers.IntegerField()
    host_label = serializers.CharField()
    serial_number = serializers.CharField(allow_null=True)
    vendor_name = serializers.CharField(allow_blank=True, allow_null=True)
    purchased_on = serializers.DateField(allow_null=True)
    warranty_expires_on = serializers.DateField(allow_null=True)
    status = serializers.CharField()
    document_count = serializers.IntegerField()


class WarrantyReportQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[value for value, _label in STATUS_CHOICES],
        required=False,
    )
    missing_docs = serializers.BooleanField(required=False)
    expires_before = serializers.DateField(required=False)
