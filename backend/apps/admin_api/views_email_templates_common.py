from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from apps.accounts import rbac
from apps.integrations.email_streams import (
    MACHINE_BEARING_STREAMS,
    TYPE_OVERRIDABLE_AUDIENCES,
)
from apps.integrations.email_templates_registry import (
    REGISTRY,
    get_entry,
    iter_entries,
    validate_email_template_strings,
)
from apps.integrations.models import EmailTemplate, MachineTypeEmailTemplate
from apps.machines import role_scope
from apps.machines.models import MachineType
from apps.machines.printer_capabilities import PRINTER_SLUG
from apps.makerspaces.models import Makerspace

from .serializers_email_templates import (
    EmailTemplateDetailSerializer,
    EmailTemplateListItemSerializer,
    EmailTemplatePreviewRequestSerializer,
    EmailTemplatePreviewResponseSerializer,
    EmailTemplateUpdateSerializer,
    MachineTypeOptionSerializer,
)

STREAM_ACTIONS = {
    "hardware": (rbac.Action.EDIT_INVENTORY, rbac.Action.MANAGE_MAKERSPACE),
    "printing": (rbac.Action.MANAGE_PRINTING, rbac.Action.MANAGE_MAKERSPACE),
    "events": (rbac.Action.MANAGE_EVENTS, rbac.Action.MANAGE_MAKERSPACE),
    "bookings": (rbac.Action.MANAGE_BOOKINGS, rbac.Action.MANAGE_MAKERSPACE),
    "maintenance": (rbac.Action.MANAGE_MACHINES, rbac.Action.MANAGE_MAKERSPACE),
    "membership": (rbac.Action.MANAGE_MAKERSPACE,),
}

STREAM_MODULES = {
    "events": "events",
    "bookings": "bookings",
    "maintenance": "maintenance",
    "membership": "membership",
}

def _stream_module_available(makerspace, stream):
    key = STREAM_MODULES.get(stream)
    if key is None:
        return True
    try:
        from apps.makerspaces.platform import module_enabled

        return bool(module_enabled(makerspace, key))
    except Exception:
        return True


def _resolve_makerspace(actor, makerspace_id, stream):
    actions = STREAM_ACTIONS.get(stream)
    if actions is None:
        raise Http404
    scope = rbac.makerspaces_for_actions(actor, *actions)
    qs = Makerspace.objects.filter(pk=makerspace_id)
    if scope is not rbac.ALL:
        qs = qs.filter(id__in=scope) if scope else qs.none()
    makerspace = qs.first()
    if makerspace is None or not _stream_module_available(makerspace, stream):
        raise Http404
    return makerspace
def email_template_type_scope(actor, makerspace_id, stream):
    """None is unrestricted; a set (including empty) is narrowed type authority.

    Only the machine-bearing streams are narrowed. Roles here are editable and
    action-based, so a custom role can hold `EDIT_INVENTORY` or `MANAGE_EVENTS` *and* a
    scoped `MANAGE_MACHINES`; narrowing a stream it is independently authorized for would
    revoke that grant rather than scope machine wording -- and because a non-machine
    stream has no firing types, "narrowed" there collapses to "reaches nothing" and the
    stream disappears entirely. Same mixed-role rule as the dashboard's non-machine
    counters and `procurement.access.machine_type_scope`.
    """
    if stream not in MACHINE_BEARING_STREAMS:
        return None
    if not rbac.can(actor, rbac.Action.MANAGE_MACHINES, makerspace_id):
        return None
    scope = role_scope.manage_scope_for(actor, makerspace_id)
    if scope is role_scope.EXEMPT:
        return None
    if stream == "printing" and role_scope.role_grants_directly(
        actor, makerspace_id, rbac.Action.MANAGE_PRINTING
    ):
        return None
    type_ids, _machine_ids = scope
    return set(type_ids)
_UNRESOLVED_SCOPE = object()


def _firing_type_queryset(
    actor, makerspace, stream, audience, *, type_scope=_UNRESOLVED_SCOPE
):
    if audience not in TYPE_OVERRIDABLE_AUDIENCES.get(stream, ()):
        return MachineType.objects.none()
    if stream == "printing":
        qs = MachineType.objects.filter(makerspace__isnull=True, slug=PRINTER_SLUG)
    elif stream == "maintenance":
        qs = MachineType.objects.filter(
            Q(makerspace__isnull=True) | Q(makerspace=makerspace)
        )
    else:
        return MachineType.objects.none()
    if type_scope is _UNRESOLVED_SCOPE:
        type_scope = email_template_type_scope(actor, makerspace.pk, stream)
    if type_scope is not None:
        qs = qs.filter(pk__in=type_scope)
    return qs.order_by("name", "pk")
def _resolve_type(actor, makerspace, stream, audience, key, machine_type_id):
    if (stream, audience, key) not in REGISTRY:
        raise Http404
    return get_object_or_404(
        _firing_type_queryset(actor, makerspace, stream, audience),
        pk=machine_type_id,
    )


def _require_space_default(actor, makerspace_id, stream):
    if email_template_type_scope(actor, makerspace_id, stream) is not None:
        raise Http404


def _visible_streams(actor, makerspace_id):
    streams = []
    for stream in STREAM_ACTIONS:
        try:
            makerspace = _resolve_makerspace(actor, makerspace_id, stream)
        except Http404:
            continue
        type_scope = email_template_type_scope(actor, makerspace_id, stream)
        if type_scope is not None and not any(
            _firing_type_queryset(
                actor, makerspace, stream, audience, type_scope=type_scope
            ).exists()
            for audience in TYPE_OVERRIDABLE_AUDIENCES.get(stream, ())
        ):
            continue
        streams.append(stream)
    return streams


def _space_detail_payload(makerspace, stream, audience, key):
    entry = get_entry(stream, audience, key)
    if entry is None:
        raise Http404
    row = EmailTemplate.objects.filter(
        makerspace=makerspace, stream=stream, audience=audience, key=key
    ).first()
    return {
        "stream": stream, "audience": audience, "key": key,
        "label": entry.label, "description": entry.description, "fields": entry.fields,
        "subject": row.subject if row else entry.default_subject,
        "text_body": row.text_body if row else entry.default_text,
        "html_body": row.html_body if row else entry.default_html,
        "is_active": row.is_active if row else True, "is_overridden": row is not None,
        "default_subject": entry.default_subject, "default_text": entry.default_text,
        "default_html": entry.default_html,
    }


def _effective_space_strings(makerspace, stream, audience, key):
    entry = get_entry(stream, audience, key)
    row = EmailTemplate.objects.filter(
        makerspace=makerspace, stream=stream, audience=audience, key=key, is_active=True
    ).first()
    if row is not None:
        try:
            validate_email_template_strings(
                stream, audience, key, row.subject, row.text_body, row.html_body
            )
        except DjangoValidationError:
            row = None
    if row is None:
        return entry.default_subject, entry.default_text, entry.default_html
    return row.subject, row.text_body, row.html_body


def _type_detail_payload(makerspace, machine_type, stream, audience, key):
    entry = get_entry(stream, audience, key)
    fallback = _effective_space_strings(makerspace, stream, audience, key)
    row = MachineTypeEmailTemplate.objects.filter(
        makerspace=makerspace, machine_type=machine_type, stream=stream,
        audience=audience, key=key,
    ).first()
    return {
        "stream": stream, "audience": audience, "key": key,
        "label": entry.label, "description": entry.description, "fields": entry.fields,
        "subject": row.subject if row else fallback[0],
        "text_body": row.text_body if row else fallback[1],
        "html_body": row.html_body if row else fallback[2],
        "is_active": row.is_active if row else True, "is_overridden": row is not None,
        "default_subject": fallback[0], "default_text": fallback[1],
        "default_html": fallback[2],
    }


def _list_payload(actor, makerspace, visible_streams):
    scopes = {
        stream: email_template_type_scope(actor, makerspace.pk, stream)
        for stream in visible_streams
    }
    default_streams = [stream for stream, scope in scopes.items() if scope is None]
    space_rows = {(r.stream, r.audience, r.key): r for r in EmailTemplate.objects.filter(
        makerspace=makerspace, stream__in=default_streams
    )}
    type_rows = {(r.stream, r.audience, r.key, r.machine_type_id): r for r in
        MachineTypeEmailTemplate.objects.filter(makerspace=makerspace, stream__in=visible_streams)}
    # Materialized once per (stream, audience): the firing types vary by coordinate but NOT
    # by key, and the registry holds many keys per coordinate -- resolving inside the loop
    # issued one MachineType query per notification event (18 on today's registry) and grew
    # with every event added.
    firing_types = {
        (stream, audience): list(
            _firing_type_queryset(
                actor, makerspace, stream, audience, type_scope=scopes[stream]
            )
        )
        for stream in visible_streams
        for audience in TYPE_OVERRIDABLE_AUDIENCES.get(stream, ())
    }
    payload = []
    for (stream, audience, key), entry in iter_entries():
        if stream not in visible_streams:
            continue
        type_scope = scopes[stream]
        can_edit_default = type_scope is None
        types = []
        for machine_type in firing_types.get((stream, audience), ()):
            row = type_rows.get((stream, audience, key, machine_type.pk))
            types.append({"id": machine_type.pk, "name": machine_type.name,
                          "is_active": row.is_active if row else True,
                          "is_overridden": row is not None})
        if not can_edit_default and not types:
            continue
        row = space_rows.get((stream, audience, key))
        # A narrowed actor cannot read the space row. These flags therefore describe no
        # selectable row; per-type flags above drive every badge they can actually see.
        payload.append({
            "stream": stream, "audience": audience, "key": key, "label": entry.label,
            "is_active": row.is_active if row and can_edit_default else True,
            "is_overridden": row is not None if can_edit_default else False,
            "can_edit_space_default": can_edit_default, "overridable_types": types,
        })
    return sorted(payload, key=lambda item: (item["stream"], item["audience"], item["key"]))
