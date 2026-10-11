from rest_framework import serializers
from apps.events.models import EventRegistration
from apps.admin_api.serializers_payment_summary import PaymentSummaryMixin


class EventRegistrationAdminSerializer(PaymentSummaryMixin, serializers.ModelSerializer):
    event_id = serializers.IntegerField(read_only=True)
    ticket_type_id = serializers.IntegerField(read_only=True, allow_null=True)
    payment = serializers.SerializerMethodField()

    class Meta:
        model = EventRegistration
        fields = (
            'id', 'event_id', 'name', 'email', 'phone', 'custom_answers',
            'status', 'created_at', 'payment', 'ticket_type_id', 'quoted_amount', 'discount_amount',
        )
        read_only_fields = fields


class EventStaffRegistrationSerializer(serializers.Serializer):
    """Staff registering an identified account under the event's audience rules.

    `member_id` only. Contact details are copied off the account by the registration
    service, so a staffer cannot record an attendee under a name and email that belong
    to nobody — which is what makes the attendee list usable as an accountability record
    rather than free text.
    """

    member_id = serializers.IntegerField(min_value=1)
    invite_code = serializers.CharField(max_length=128, required=False, write_only=True)
    ticket_type_id = serializers.IntegerField(min_value=1, required=False)
    promo_code = serializers.CharField(max_length=128, required=False, write_only=True)
    custom_answers = serializers.JSONField(required=False, allow_null=True)
    # Used only when the account carries no number of its own. A registration must have
    # a contact number, so without this a member who never entered one could not be
    # registered by anybody — a dead end the person at the desk can simply ask about.
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default='')
    # Same fallback shape, for the same reason: `EventRegistration.email` is non-blank,
    # and a walk-in may have been created with a name and nothing else. Without this,
    # exactly the members this program made registrable could never be registered.
    email = serializers.EmailField(required=False, allow_blank=True, default='')


class EventEligibleMemberSerializer(serializers.Serializer):
    """A picker row. Name and id only — a roster is not a contact export."""

    member_id = serializers.IntegerField(min_value=1)
    display_name = serializers.CharField()
