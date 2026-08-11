"""Staff API serializers for machine service requests."""

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.machines.models import MachineServiceRequest
from apps.payments.models import Payment
from apps.payments.serializers import StaffPaymentSerializer


class ServiceRequesterSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    display = serializers.SerializerMethodField()

    def get_display(self, user) -> str:
        return user.get_full_name().strip() or user.username


class ServiceMachineSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class ServiceFileSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.CharField(read_only=True)
    original_filename = serializers.CharField(read_only=True)
    content_type = serializers.CharField(read_only=True)
    size_bytes = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    attached_at = serializers.DateTimeField(read_only=True)


class ServiceConsumptionSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    machine_consumable_id = serializers.IntegerField(read_only=True)
    measurement = serializers.CharField(read_only=True)
    product_id = serializers.IntegerField(read_only=True, allow_null=True)
    label = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    outcome = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class MachineServiceRequestSerializer(serializers.ModelSerializer):
    machine = ServiceMachineSerializer(source="bucket.machine", read_only=True)
    assigned_machine = ServiceMachineSerializer(read_only=True)
    requester = ServiceRequesterSerializer(read_only=True)
    bucket_id = serializers.IntegerField(read_only=True)
    queue_id = serializers.IntegerField(read_only=True)
    machine_type = serializers.SerializerMethodField()
    capability_payload = serializers.JSONField(read_only=True)
    metering_unit = serializers.CharField(read_only=True, allow_null=True)
    planned_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    reserved_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    actual_consumed_quantity = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    planned_grams = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    reserved_grams = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    actual_consumed_grams = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    payment = serializers.SerializerMethodField()
    run_machine_model = serializers.CharField(read_only=True)
    files = ServiceFileSerializer(many=True, read_only=True)
    consumptions = ServiceConsumptionSerializer(many=True, read_only=True)

    class Meta:
        model = MachineServiceRequest
        fields = (
            "id", "bucket_id", "queue_id", "machine_type", "machine", "assigned_machine", "requester",
            "requester_name", "contact_email", "contact_phone", "title",
            "description", "source_link", "status", "reason", "estimated_minutes",
            "actual_minutes", "fail_percent_complete", "accepted_at", "started_at",
            "completed_at", "failed_at", "collected_at", "created_at", "updated_at",
            "capability_payload", "metering_unit", "planned_quantity", "reserved_quantity", "actual_consumed_quantity", "planned_grams", "reserved_grams", "actual_consumed_grams", "payment", "run_machine_model", "files", "consumptions",
        )
        read_only_fields = fields

    def get_machine_type(self, obj) -> str:
        if obj.queue_id:
            return obj.queue.machine_type.slug
        machine = obj.assigned_machine or (obj.bucket.machine if obj.bucket_id else None)
        return machine.machine_type.slug if machine else ""

    @extend_schema_field(StaffPaymentSerializer(allow_null=True))
    def get_payment(self, obj):
        payment_map = self.context.get("payments_by_subject_id")
        payment = payment_map.get(obj.pk) if payment_map is not None else Payment.objects.filter(
            makerspace_id=obj.makerspace_id,
            subject_type=Payment.SubjectType.MACHINE_SERVICE_REQUEST,
            subject_id=obj.pk,
        ).first()
        return StaffPaymentSerializer(
            payment,
            # Keyed `(subject_type, subject_id)` and valued `(label, makerspace_id,
            # member_id)` to match what `resolve_subject_labels` returns. A bare `obj.pk`
            # key never matched, so this surface had always silently fallen back to the
            # generic display -- and now that machine-service deliberately snapshots no
            # `subject_label` (the title is member-typed free text), this is the only place
            # left that names the job. Staff already read the title on this same row.
            context={
                "payment_subject_labels": {
                    (Payment.SubjectType.MACHINE_SERVICE_REQUEST, obj.pk): (
                        obj.title,
                        obj.makerspace_id,
                        None,
                    )
                }
            },
        ).data if payment else None


class MachineServiceSubmitSerializer(serializers.Serializer):
    requester_id = serializers.IntegerField(min_value=1)
    machine_id = serializers.IntegerField(min_value=1)
    title = serializers.CharField(max_length=200, trim_whitespace=True)
    description = serializers.CharField(required=False, allow_blank=True)
    source_link = serializers.URLField(required=False, allow_blank=True)
    requester_name = serializers.CharField(required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    capability_payload = serializers.JSONField(required=False)


class ServiceAcceptSerializer(serializers.Serializer):
    estimated_minutes = serializers.IntegerField(required=False, min_value=0)
    planned_grams = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    note = serializers.CharField(required=False, allow_blank=True)


class ServiceRejectSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class ServiceStartSerializer(serializers.Serializer):
    machine_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    estimated_minutes = serializers.IntegerField(required=False, min_value=0)
    consumable_pool_id = serializers.IntegerField(required=False, min_value=1)
    planned_grams = serializers.DecimalField(
        required=False, max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )
    planned_quantity = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0.01"))


class ServiceConsumptionInputSerializer(serializers.Serializer):
    machine_consumable_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0.01")
    )


class ServiceCompleteSerializer(serializers.Serializer):
    actual_minutes = serializers.IntegerField(min_value=0)
    actual_grams = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    actual_quantity = serializers.DecimalField(required=False, max_digits=12, decimal_places=2, min_value=Decimal("0"))
    consumptions = ServiceConsumptionInputSerializer(many=True, required=False, default=list)


class ServiceFailSerializer(ServiceCompleteSerializer):
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)
    percent_complete = serializers.IntegerField(min_value=0, max_value=100)


class EmptyServiceActionSerializer(serializers.Serializer):
    pass


class ServiceFilePresignSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=128)


class ServiceFileUploadSerializer(serializers.Serializer):
    url = serializers.URLField()
    method = serializers.CharField(required=False)
    fields = serializers.DictField(required=False)
    headers = serializers.DictField(required=False)


class ServiceFilePresignResponseSerializer(serializers.Serializer):
    file_id = serializers.IntegerField()
    upload = ServiceFileUploadSerializer()


class ServiceFileFinalizeSerializer(serializers.Serializer):
    file_id = serializers.IntegerField(min_value=1)


class ServiceFileFinalizeResponseSerializer(serializers.Serializer):
    file_id = serializers.IntegerField()


class ServiceFileUrlSerializer(serializers.Serializer):
    url = serializers.URLField()
