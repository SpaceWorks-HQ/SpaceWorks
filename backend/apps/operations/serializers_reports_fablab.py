from rest_framework import serializers

from apps.operations.serializers_reports_base import ReportRowsFieldMixin, TypedReportBaseSerializer


class MachineUsageRowSerializer(TypedReportBaseSerializer):
    machine_id = serializers.IntegerField()
    machine_name = serializers.CharField()
    machine_type = serializers.CharField()
    is_active = serializers.BooleanField()
    usage_entries = serializers.IntegerField()
    usage_hours = serializers.DecimalField(max_digits=20, decimal_places=2)


class EventAttendanceRowSerializer(TypedReportBaseSerializer):
    event_id = serializers.IntegerField()
    title = serializers.CharField()
    starts_at = serializers.DateTimeField()
    status = serializers.CharField()
    capacity = serializers.IntegerField()
    registrations = serializers.IntegerField()
    confirmed = serializers.IntegerField()
    registered = serializers.IntegerField()
    waitlisted = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    attended = serializers.IntegerField()
    attendance_rate_percent = serializers.FloatField(allow_null=True)
    organizers = serializers.CharField(allow_blank=True)


class BookingUtilizationRowSerializer(TypedReportBaseSerializer):
    space_id = serializers.IntegerField()
    space_name = serializers.CharField()
    kind = serializers.CharField()
    is_active = serializers.BooleanField()
    booked = serializers.IntegerField()
    completed = serializers.IntegerField()
    no_show = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    upcoming = serializers.IntegerField()
    reserved_hours = serializers.DecimalField(max_digits=20, decimal_places=2)
    completed_hours = serializers.DecimalField(max_digits=20, decimal_places=2)
    window_hours = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    reservation_utilization_percent = serializers.FloatField(allow_null=True)
    no_show_rate_percent = serializers.FloatField(allow_null=True)


class MaintenanceActivityRowSerializer(TypedReportBaseSerializer):
    machine_id = serializers.IntegerField()
    machine_name = serializers.CharField()
    machine_type = serializers.CharField()
    is_active = serializers.BooleanField()
    log_count = serializers.IntegerField()
    costed_log_count = serializers.IntegerField()
    total_cost = serializers.DecimalField(max_digits=20, decimal_places=2)
    average_cost = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    last_performed_at = serializers.DateTimeField(allow_null=True)
    average_interval_days = serializers.FloatField(allow_null=True)
    active_schedules = serializers.IntegerField()
    overdue_schedules = serializers.IntegerField()


class FabLabHealthRowSerializer(TypedReportBaseSerializer):
    events_enabled = serializers.BooleanField()
    events_available = serializers.BooleanField()
    events_in_period = serializers.IntegerField(allow_null=True)
    events_registrations = serializers.IntegerField(allow_null=True)
    events_attended = serializers.IntegerField(allow_null=True)
    events_completed_attendance_rate_percent = serializers.FloatField(allow_null=True)
    bookings_enabled = serializers.BooleanField()
    bookings_available = serializers.BooleanField()
    bookings_active_spaces = serializers.IntegerField(allow_null=True)
    bookings_non_cancelled = serializers.IntegerField(allow_null=True)
    bookings_reserved_hours = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    bookings_upcoming = serializers.IntegerField(allow_null=True)
    bookings_no_shows = serializers.IntegerField(allow_null=True)
    bookings_reservation_utilization_percent = serializers.FloatField(allow_null=True)
    machines_enabled = serializers.BooleanField()
    machines_available = serializers.BooleanField()
    machines_active = serializers.IntegerField(allow_null=True)
    machines_usage_hours = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    maintenance_enabled = serializers.BooleanField()
    maintenance_available = serializers.BooleanField()
    maintenance_logs = serializers.IntegerField(allow_null=True)
    maintenance_total_cost = serializers.DecimalField(max_digits=20, decimal_places=2, allow_null=True)
    maintenance_overdue_schedules = serializers.IntegerField(allow_null=True)


class MemberActivityRowSerializer(TypedReportBaseSerializer):
    makerspace_name = serializers.CharField()
    membership_policy = serializers.CharField()
    referrals_enabled = serializers.BooleanField()
    new_members = serializers.IntegerField(help_text="Current activated_at values in the selected [start, end) range, not event history.")
    active_members = serializers.IntegerField(help_text="Current membership snapshot.")
    revoked_members = serializers.IntegerField(help_text="Current revoked_at values in the selected [start, end) range, not event history.")
    pending_requests = serializers.IntegerField(help_text="Current membership-request snapshot.")
    open_invites = serializers.IntegerField(help_text="Current membership-request snapshot.")
    referred_joins = serializers.IntegerField(help_text="Active automatic referrals with decided_at in the selected [start, end) range.")
    verified_members = serializers.IntegerField(help_text="Current verified_at snapshot.")


def _report_serializer(name, row_serializer):
    return type(name, (ReportRowsFieldMixin,), {"typed_rows": row_serializer(many=True)})


MachineUsageReportSerializer = _report_serializer("MachineUsageReportSerializer", MachineUsageRowSerializer)
EventAttendanceReportSerializer = _report_serializer("EventAttendanceReportSerializer", EventAttendanceRowSerializer)
BookingUtilizationReportSerializer = _report_serializer("BookingUtilizationReportSerializer", BookingUtilizationRowSerializer)
MaintenanceActivityReportSerializer = _report_serializer("MaintenanceActivityReportSerializer", MaintenanceActivityRowSerializer)
FabLabHealthReportSerializer = _report_serializer("FabLabHealthReportSerializer", FabLabHealthRowSerializer)
MemberActivityReportSerializer = _report_serializer("MemberActivityReportSerializer", MemberActivityRowSerializer)


class ReportErrorSerializer(serializers.Serializer):
    detail = serializers.CharField()
    code = serializers.CharField(required=False)
