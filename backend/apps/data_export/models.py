"""Literal model classification, plus the source-deployment export job."""

import uuid

from django.conf import settings
from django.db import models

from .types import Exported, GlobalReference, NotTenantData, OmittedModel

# Field names are deliberately literal.  Building this from ``_meta`` would make a new
# database column export itself before a security review could classify it.
EXPORTED_MODEL_FIELDS = {
    "apiclients.ApiClient": "id label client_id secret_encrypted client_type scopes rate_limit_tier makerspace allowed_origins is_active created_by created_at updated_at",
    "apiclients.ApiKeyRequest": "id makerspace requester label reason allowed_origins status resolution_note resolved_by resolved_at created_at updated_at",
    "audit.AuditLog": "id actor action target_type target_id makerspace meta created_at",
    "bookings.BookableSpace": "id public_token makerspace name kind description capacity location image_key is_public show_public_availability show_public_booker_names approval_mode custom_form requester_notifications_enabled payment_amount min_booking_duration_minutes max_booking_duration_minutes booking_lead_time_minutes max_booking_advance_days is_active created_by created_at updated_at",
    "bookings.Booking": "id space public_token name email phone member starts_at ends_at status note custom_answers created_at",
    "boxes.Box": "id makerspace parent code label location description is_active created_at updated_at",
    "boxes.BoxScan": "id makerspace box request actor context created_at",
    "boxes.QrCode": "id makerspace payload target_type target_id status created_by revoked_at created_at updated_at",
    "boxes.QrScanEvent": "id makerspace qr_code request actor context created_at",
    "events.Event": "id public_token makerspace title description starts_at ends_at location location_kind custom_form capacity payment_amount is_public image_key status created_by created_at updated_at",
    "events.EventCollaborator": "id event makerspace status invited_by responded_by created_at responded_at",
    "events.EventRegistration": "id event checkin_token name email phone member registered_via_makerspace payment_via_makerspace host_waiver host_waiver_accepted_at host_waiver_version_accepted email_exact_hash email_hash_generation custom_answers status created_at",
    "evidence.EvidencePhoto": "id makerspace evidence_type object_key content_type size_bytes uploaded_by created_at",
    "hardware_requests.HardwareRequest": "id makerspace requester requester_username requester_name requester_contact_email requester_contact_phone status requested_for rejection_reason accepted_by accepted_at assigned_box issued_by issued_at return_due_at return_reminder_sent_at issue_evidence issue_remark closed_by closed_at public_token created_at updated_at",
    "hardware_requests.HardwareRequestItem": "id request product requested_quantity accepted_quantity issued_quantity returned_quantity damaged_quantity missing_quantity needs_fix_quantity",
    "hardware_requests.HardwareRequestItemAsset": "id request_item asset outcome issued_at returned_at return_event",
    "hardware_requests.PublicProblemReport": "id makerspace loan request requester note outcome triage_note created_at resolved_at resolved_by",
    "hardware_requests.PublicToolLoan": "id makerspace qr_code container request requester target_type target_id target_label asset_ids qr_ids status source checked_out_at due_at returned_at return_evidence return_notes",
    "hardware_requests.RequesterAccountability": "id requester request request_item makerspace issue_type description evidence_photo quantity created_by created_at",
    "hardware_requests.ReturnEvent": "id request makerspace box evidence remark actor created_at",
    "integrations.ChatTemplate": "id makerspace feature event text_body is_active updated_by created_at updated_at",
    "integrations.DestinationCategoryScope": "id destination category",
    "integrations.DestinationMachineScope": "id destination machine",
    "integrations.DestinationMachineTypeScope": "id destination machine_type",
    "integrations.EmailNotificationMute": "id makerspace target stream event audience created_at created_by",
    "integrations.EmailTemplate": "id stream audience key makerspace subject text_body html_body is_active created_at updated_at",
    "integrations.MachineTypeEmailTemplate": "id stream audience key makerspace machine_type subject text_body html_body is_active created_at updated_at",
    "integrations.NotificationDestination": "id makerspace channel label webhook_url telegram_chat_id is_active created_at updated_at",
    "integrations.NotificationPreference": "id makerspace feature channel enabled updated_by created_at updated_at",
    "integrations.NotificationRecipient": "id makerspace feature event kind role user created_at created_by",
    "integrations.RecipientCategoryScope": "id recipient category",
    "integrations.RecipientMachineScope": "id recipient machine",
    "integrations.RecipientMachineTypeScope": "id recipient machine_type",
    "inventory.Category": "id makerspace name slug display_order icon created_at updated_at",
    "inventory.InventoryAsset": "id makerspace product box asset_tag serial_number status public_self_checkout_enabled notes created_at updated_at",
    "inventory.InventoryProduct": "id makerspace box category name description image_key tracking_mode total_quantity available_quantity reserved_quantity issued_quantity damaged_quantity lost_quantity needs_fix_quantity is_public public_self_checkout_enabled show_public_count public_availability_mode storage_location is_archived created_at updated_at",
    "machines.Machine": "id makerspace machine_type name location notes status firmware_version camera_feed_url image_key is_public is_active service_file_policy type_payload legacy_print_printer_id created_at updated_at created_by",
    "machines.MachineConsumable": "id machine measurement product label remaining low_threshold note created_by created_at",
    "machines.MachineConsumableAdjustment": "id consumable_pool makerspace kind quantity_delta metering_unit consumed_quantity service_request usage_entry reason created_by created_at legacy_filament_adjustment_id",
    "machines.MachineConsumablePool": "id makerspace machine material color brand unit lot_code initial_grams remaining_grams low_threshold_grams is_active opened_at legacy_filament_spool_id created_by created_at updated_at",
    "machines.MachineDocument": "id machine doc_type object_key original_filename content_type size_bytes uploaded_by created_at",
    "machines.MachineErrorLog": "id machine severity message logged_by created_at",
    "machines.MachineOperator": "id machine user access_level assigned_by assigned_at",
    "machines.MachineServiceRequest": "id bucket queue makerspace requester member requester_name contact_email contact_phone public_token legacy_print_request_id title description source_link status reason assigned_machine handled_by accepted_by accepted_at started_at completed_at collected_by collected_at failed_at estimated_minutes actual_minutes fail_percent_complete capability_payload planned_grams reserved_grams actual_consumed_grams metering_unit planned_quantity reserved_quantity actual_consumed_quantity run_consumable_pool payment_amount payment_status paid_at run_machine_name run_machine_model run_consumable_label run_consumable_material run_consumable_color run_estimated_minutes run_planned_grams reprint_of created_at updated_at",
    "machines.MachineType": "id makerspace slug name icon is_builtin managing_action capability_config",
    "machines.MachineUsageEntry": "id machine hours source note service_request consumable_pool duration_minutes outcome percent_complete reason consumed_grams metering_unit consumed_quantity legacy_manual_print_log_id title requester_name contact_email contact_phone logged_by created_at",
    "machines.MakerspaceMachineTypePricing": "id makerspace machine_type rate_per_unit flat_fee payment_enabled created_by updated_by created_at updated_at",
    "machines.RoleMachineScope": "id role machine created_at",
    "machines.RoleMachineTypeScope": "id role machine_type created_at",
    "machines.ServiceBucket": "id machine name description is_active created_at updated_at",
    "machines.ServiceQueue": "id makerspace machine_type name description is_active capacity allocation_policy legacy_print_bucket_id created_at updated_at",
    "machines.ServiceRequestConsumption": "id service_request machine_consumable measurement product label quantity created_by created_at outcome",
    "machines.ServiceRequestFile": "id service_request makerspace machine queue kind object_key content_type original_filename size_bytes owner_user_id file_policy_name file_policy_version created_at attached_at legacy_print_request_file_id",
    "maintenance.MaintenanceLog": "id machine performed_by performed_at summary cost parts_note created_at",
    "maintenance.MaintenanceLogDocument": "id log object_key size_bytes uploaded_by created_at",
    "maintenance.MaintenanceSchedule": "id machine description interval_days next_due is_active created_by created_at updated_at",
    "makerspaces.Makerspace": "id name slug public_code location map_url geofence_latitude geofence_longitude geofence_radius_m geofence_enabled public_inventory_enabled public_stats_enabled public_stats_show_holder_names public_print_status_lookup_policy membership_policy membership_dues_amount referrals_enabled filament_low_stock_threshold_grams superadmin_access_enabled staff_notifications_enabled booking_requester_notifications_enabled logo_key cover_image_key frontend_domain frontend_domain_status domain_verification_token domain_verified_at frontend_domain_changed_at hidden_from_central_directory public_api_key cors_allowed_origins enabled_modules enabled_features resource_limit_overrides storage_bytes_used theme_config branding_config telegram_group_chat_id telegram_bot_token smtp_host smtp_port smtp_username smtp_password smtp_use_tls smtp_use_ssl smtp_from_email slack_webhook_url mattermost_webhook_url discord_webhook_url default_loan_days presence_preset_minutes created_by archived_at archived_by created_at updated_at",
    "makerspaces.MakerspaceMembership": "id makerspace user role assigned_role receives_notifications can_refer can_verify verified_at verified_by status activated_at activated_by revoked_at revoked_by revocation_reason waiver_accepted_at waiver_version_accepted accepted_waiver witnessed_waiver witnessed_waiver_version witnessed_at witnessed_by witnessed_actor_snapshot verified_actor_snapshot activated_actor_snapshot revoked_actor_snapshot created_at",
    "makerspaces.MakerspaceRole": "id makerspace name slug granted_actions legacy_role is_default is_protected created_at updated_at",
    "makerspaces.MakerspaceWaiver": "id makerspace body version is_active created_by created_at superseded_at",
    "makerspaces.MemberProfile": "id membership is_visible show_attended_events headline institution bio avatar_key interests languages education github_username github_contributions github_synced_at created_at updated_at",
    "makerspaces.MemberProject": "id profile title description image_key links position created_at updated_at",
    "makerspaces.MembershipRequest": "id makerspace user invite_email kind state requested_by invited_by decided_by assigned_role auto_activate_on_claim decision_note created_at decided_at updated_at",
    "notifications.Notification": "id makerspace level event title body url_path read_at created_at",
    "operations.InventoryAdjustment": "id makerspace stocktake transfer product asset delta_available delta_damaged delta_lost reason created_by created_at",
    "operations.QrPrintBatch": "id makerspace title status created_by created_at printed_at",
    "operations.QrPrintBatchItem": "id batch qr_code label_text target_type target_id sort_order",
    "operations.StocktakeLedgerEntry": "id makerspace stocktake line product asset bucket delta old_asset_status new_asset_status reason created_by created_at",
    "operations.StocktakeLine": "id stocktake product asset container expected_quantity counted_quantity variance_quantity condition notes",
    "operations.StocktakeSession": "id makerspace container status started_by approved_by started_at completed_at approved_at notes",
    "operations.StockTransfer": "id makerspace source_container destination_container source_makerspace destination_makerspace created_by reason status created_at applied_at",
    "operations.StockTransferLine": "id transfer product asset quantity from_status to_status notes",
    "payments.MakerspacePaymentSettings": "id makerspace provider stripe_publishable_key stripe_secret_key stripe_webhook_secret default_currency connect_account_id connect_status connect_charges_enabled connect_payouts_enabled connect_account_assigned_at connect_status_updated_at razorpay_key_id razorpay_key_secret razorpay_webhook_secret",
    "payments.Payment": "id makerspace subject_type subject_id member via_makerspace subject_label amount currency status provider external_order_id external_payment_id checkout_url stripe_provider stripe_connected_account_id stripe_application_fee_amount online_rail stripe_checkout_session_id stripe_checkout_url stripe_checkout_session_expired_at stripe_payment_intent_id created_by created_at updated_at",
    "presence.PresenceSession": "id member makerspace membership started_at expires_at ended_at ended_by end_reason",
    "procurement.ToBuyItem": "id makerspace machine_type kind name quantity link status estimated_unit_cost vendor_name actual_unit_cost purchaser ordered_at received_at moved_to_inventory_at resulting_product resulting_pool resulting_machine source_pool created_by created_at updated_at",
    "procurement.ToBuyReceipt": "id to_buy_item object_key uploaded_by created_at",
    "warranty.Warranty": "id makerspace asset machine purchased_on warranty_expires_on vendor_name vendor_contact created_at updated_at",
    "warranty.WarrantyDocument": "id warranty object_key original_filename content_type size_bytes uploaded_by created_at",
}

EXPORTED_MODELS = frozenset(EXPORTED_MODEL_FIELDS)

GLOBAL_MODELS = {
    "accounts.User": GlobalReference(
        "Only the user closure is projected; the platform-global table is never tenant-owned."
    )
}

OMITTED_MODELS = {
    "accounts.DailyOtpEmailCounter": "Platform authentication telemetry.",
    "accounts.DeviceAttestationChallenge": "Transient authentication state.",
    "accounts.DeviceGrant": "Live bearer-session authority.",
    "accounts.DeviceRefreshFamily": "Live bearer-session authority.",
    "accounts.DeviceRefreshToken": "Live bearer-session authority.",
    "accounts.EmailVerificationChallenge": "Transient authentication state.",
    "accounts.OidcProvider": "Platform identity configuration.",
    "accounts.PhoneVerificationChallenge": "Transient authentication state.",
    "accounts.PlatformLoginMethods": "Platform identity configuration.",
    "accounts.PlatformSocialAuthSettings": "Platform credentials and identity configuration.",
    "accounts.SocialIdentity": "Verified platform login identity.",
    "accounts.SocialLoginNonce": "Transient authentication state.",
    "admin_api.BulkImportJob": "Arbitrary upload and unschematized JSON rows.",
    "encryption.MakerspaceEncryptionKey": "Encryption key material never enters a manager export.",
    "encryption.PiiBlindIndex": "Deployment-local derived identity index.",
    "encryption.PiiGlobalWriteFence": "Platform coordination state.",
    "encryption.PiiMakerspaceWriteFence": "Deployment coordination state.",
    "encryption.SearchKeyGeneration": "Deployment-local cryptographic state.",
    "integrations.DailyEmailCounter": "Delivery telemetry.",
    "integrations.DailyNotificationCounter": "Delivery telemetry.",
    "integrations.DailyOtpSmsCounter": "Platform delivery telemetry.",
    "integrations.EmailLog": "Delivery bodies and telemetry are not rebuild data.",
    "integrations.NotificationDeliveryLog": "Delivery payloads and telemetry are not rebuild data.",
    "integrations.PlatformEmailSettings": "Platform credentials.",
    "integrations.PlatformPushSettings": "Platform credentials.",
    "integrations.PlatformSmsSettings": "Platform credentials.",
    "integrations.PushDevice": "Live device bearer destination.",
    "machines.PrintingCutoverRepair": "Retired migration provenance.",
    "machines.PrintingCutoverState": "Retired migration coordination state.",
    "makerspaces.MakerspaceArchiveRequest": "Source-deployment lifecycle request.",
    # Phase 7 import staging. Both are TARGET-side machinery rather than source tenant
    # data: a pending row is an archived membership waiting for its address to be proven
    # here, and a reconciliation is the operator's persisted judgement that an archived
    # person is a particular target account. The readable export omits them (Phase 4 v8
    # section 4); carrying and remapping unresolved pending rows is PORTABLE's job in 5B.
    "makerspaces.PendingImportedMembership": "Import staging awaiting target-side proof.",
    "makerspaces.ImportedUserReconciliation": "Target-side operator reconciliation input.",
    "makerspaces.SubdomainRequest": "Source-deployment routing request.",
    "operations.PeriodicTaskRun": "Deployment scheduler state.",
    "payments.PlatformStripeConnectSettings": "Platform payment credentials.",
    "payments.ProcessedStripeEvent": "Provider idempotency telemetry.",
    "payments.StripeConnectOAuthState": "Transient OAuth state.",
    "roadmap.RoadmapItem": "Platform-global product roadmap.",
    "updates.PlatformUpdateSettings": "Platform update state.",
    "data_export.DataExportJob": "Source-deployment export lifecycle and bearer state.",
}

NOT_TENANT_MODELS = {
    label: NotTenantData(reason) for label, reason in OMITTED_MODELS.items()
}
MODELS = {
    **{label: Exported() for label in EXPORTED_MODELS},
    **GLOBAL_MODELS,
    **{label: OmittedModel(value.reason) for label, value in NOT_TENANT_MODELS.items()},
}


class DataExportJob(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"

    class FailureCode(models.TextChoices):
        NONE = "", "None"
        DEADLINE_EXCEEDED = "deadline_exceeded", "Deadline exceeded"
        INTEGRITY_ERROR = "integrity_error", "Integrity error"
        STORAGE_ERROR = "storage_error", "Storage error"
        QUOTA_EXCEEDED = "quota_exceeded", "Quota exceeded"
        INTERNAL_ERROR = "internal_error", "Internal error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    makerspace = models.ForeignKey(
        "makerspaces.Makerspace", on_delete=models.CASCADE, related_name="data_export_jobs"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="data_export_jobs"
    )
    fidelity = models.CharField(max_length=16, default="REDACTED")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    object_key = models.CharField(max_length=512, unique=True)
    accounted_size_bytes = models.PositiveBigIntegerField(default=0)
    manifest = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(
        max_length=32, choices=FailureCode.choices, blank=True, default=""
    )
    failure_detail = models.CharField(max_length=500, blank=True, default="")
    deadline_at = models.DateTimeField(null=True, blank=True)
    snapshot_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    download_token_digest = models.CharField(max_length=64, blank=True, default="")
    download_token_expires_at = models.DateTimeField(null=True, blank=True)
    download_token_consumed_at = models.DateTimeField(null=True, blank=True)
    download_issued_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issued_data_export_downloads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("makerspace", "status", "created_at"))]

    def __str__(self):
        return f"{self.makerspace_id}:{self.fidelity}:{self.status}"
