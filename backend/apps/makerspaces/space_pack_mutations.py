"""Pack adapters around the established domain mutation boundaries."""
from apps.audit import services as audit
from apps.data_export.space_pack_configuration import SECTIONS
from .space_pack_validation import AUTHORED_TEXT_FIELDS, EMAIL_TEXT_FIELDS


def write_section(actor, makerspace, section, row, values):
    spec = SECTIONS[section]
    if section == "active_waiver":
        from .waiver_services import publish_waiver
        return publish_waiver(actor, makerspace, **values)
    if section == "roles":
        from .role_services import create_role, update_role
        if row:
            return update_role(makerspace=makerspace, role=row, actor=actor, **values)
        return create_role(makerspace=makerspace, actor=actor, **values)
    if section == "admission_policy":
        from .membership_admission_settings import update_settings
        return update_settings(actor, makerspace, values)
    if section == "booking_rules":
        from apps.bookings.services_spaces import create_space
        from apps.bookings.services_rules import update_booking_rules
        if row is None:
            row = create_space(makerspace=makerspace, actor=actor, name=values["name"],
                               kind="other", description="", capacity=0, location="",
                               is_public=False, audit_service=audit)
        return update_booking_rules(row, actor=actor, **{key: value for key, value in values.items() if key != "name"})
    if section == "loan_policy":
        from .loan_policy_settings import update_loan_policy
        return update_loan_policy(actor, makerspace, values)
    if section in ("categories", "item_templates", "membership_plans"):
        if section == "categories":
            from apps.admin_api.serializers_inventory_products import CategoryAdminSerializer as serializer_class
        elif section == "membership_plans":
            from apps.admin_api.serializers_membership_plans import MembershipPlanSerializer as serializer_class
        elif row:
            from apps.admin_api.serializers_inventory_products import InventoryProductAdminUpdateSerializer as serializer_class
        else:
            from apps.admin_api.serializers_inventory_products import InventoryProductAdminCreateSerializer as serializer_class
        data = {key: getattr(value, "pk", value) for key, value in values.items()}
        serializer = serializer_class(row, data=data, context={"makerspace_id": makerspace.pk})
        for name in AUTHORED_TEXT_FIELDS & serializer.fields.keys():
            serializer.fields[name].trim_whitespace = False
        serializer.is_valid(raise_exception=True)
        result = serializer.save(makerspace=makerspace)
    else:
        from django.apps import apps
        model = apps.get_model(spec.model)
        result = row or model(makerspace=makerspace)
        for key, value in values.items():
            setattr(result, key, value)
        if section in ("chat_templates", "notification_defaults"):
            result.updated_by = actor
        elif section == "email_mutes" and row is None:
            result.created_by = actor
        excluded = [key for key in EMAIL_TEXT_FIELDS if not getattr(result, key)] if section == "email_templates" else []
        result.full_clean(exclude=excluded)
        result.save()
    audit.record(actor, "makerspace.pack_configuration_updated", makerspace=makerspace,
                 target=result, meta={"section": section, "fields": sorted(values)})
    return result
