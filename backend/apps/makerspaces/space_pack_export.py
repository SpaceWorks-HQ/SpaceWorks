"""Configuration read projection. All tenant queries are action-scoped."""
import json
from django.apps import apps
from django.core.serializers.json import DjangoJSONEncoder

from apps.accounts import rbac
from apps.data_export.space_pack_configuration import (
    HOURS_FIELDS, SECTIONS, SETTINGS_FIELDS, assert_pack_classification,
)
from .space_pack_format import PackError, canonical, seal


def scoped_rows(actor, makerspace, spec):
    query = apps.get_model(spec.model).objects.filter(makerspace=makerspace)
    return rbac.scope_by_action(actor, spec.action, query)


def project_row(row, fields):
    values = {}
    for key in fields:
        value = getattr(row, key)
        if key == "category":
            value = value.slug if value else None
        elif key == "default_plan":
            value = value.name if value else None
        elif key == "granted_actions":
            value = sorted(value)
        values[key] = value
    return json.loads(json.dumps(values, cls=DjangoJSONEncoder))


def configuration_for(actor, makerspace):
    assert_pack_classification()
    config = {
        "modules": sorted(makerspace.enabled_modules or []),
        "features": sorted(makerspace.enabled_features or []),
        "settings": project_row(makerspace, SETTINGS_FIELDS),
        "opening_hours": project_row(makerspace, HOURS_FIELDS),
    }
    for name, spec in SECTIONS.items():
        if spec.module and spec.module not in config["modules"]:
            config[name] = [] if spec.identity else None
            continue
        rows = scoped_rows(actor, makerspace, spec)
        if name == "roles":
            rows = rows.filter(is_default=False, is_protected=False)
        elif name == "active_waiver":
            rows = rows.filter(is_active=True)
        elif name == "item_templates":
            rows = rows.filter(is_archived=False).select_related("category")
        elif name == "booking_rules":
            rows = rows.filter(is_active=True)
        elif name == "admission_policy":
            rows = rows.filter(configured=True).select_related("default_plan")
        elif name == "email_templates":
            from apps.admin_api.views_email_templates_common import STREAM_MODULES
            unavailable = [stream for stream, module in STREAM_MODULES.items() if module not in config["modules"]]
            rows = rows.exclude(stream__in=unavailable)
        elif name == "notification_defaults":
            from apps.integrations.dispatch_channels import channel_module_blocks
            from apps.integrations.models import NotificationChannel
            unavailable = [channel.value for channel in NotificationChannel
                           if channel_module_blocks(makerspace, channel.value)]
            rows = rows.exclude(channel__in=unavailable)
        values = [project_row(row, spec.fields) for row in rows.order_by("pk")]
        if not spec.identity:
            config[name] = values[0] if values else None
        else:
            identities = [tuple(row[key] for key in spec.identity) for row in values]
            if len(set(identities)) != len(identities):
                raise PackError("ambiguous_pack_entry", f"{name} has duplicate local names; rename them first.")
            config[name] = sorted(values, key=lambda value: canonical(value))
    return config


def export_pack(actor, makerspace):
    from .space_pack_services import authorized_space
    makerspace = authorized_space(actor, makerspace.pk)
    from .guards import require_feature
    require_feature(makerspace, "packs.import")
    pack = seal(configuration_for(actor, makerspace))
    from .space_pack_validation import validate_configuration
    validate_configuration(pack["configuration"])
    return pack
