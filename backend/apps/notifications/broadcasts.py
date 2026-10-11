"""Member communication passes current RBAC, segment, channel and personal gates."""

from django.db import transaction
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts import rbac
from apps.audit import services as audit
from apps.integrations.notify import EmailDelivery, LifecyclePayload, notify_lifecycle
from apps.makerspaces.models import MakerspaceMembership, MembershipPlan, MembershipTerm
from apps.makerspaces.platform import feature_enabled, module_enabled
from apps.notifications.inbox import InboxDelivery
from apps.notifications.models_broadcasts import MemberBroadcast


def segment_members(space, segment):
    now = timezone.now()
    rows = rbac.scope_notification_policy(MakerspaceMembership.objects.select_related('user'), makerspace_id=space.pk).filter(
        status='active', receives_notifications=True, user__is_active=True,
        user__access_status='active', user__is_tenant_dump_stub=False,
    )
    terms = rbac.scope_notification_policy(MembershipTerm.objects.all(), makerspace_id=space.pk,
                                          field='membership__makerspace_id')
    current = terms.filter(membership_id=OuterRef('pk'), starts_at__lte=now, ends_at__gt=now, status='active')
    if segment.get('plan_id'):
        if not rbac.scope_notification_policy(MembershipPlan.objects.all(), makerspace_id=space.pk).filter(pk=segment['plan_id']).exists():
            raise ValidationError({'plan_id': 'Unknown plan in this makerspace.'})
        # A lapsed-plan campaign addresses the expired plan's former members.
        # Requiring a current term here would make plan + lapsed always empty.
        plan_terms = terms.filter(membership_id=OuterRef('pk'), ends_at__lte=now) if segment.get('status') == 'lapsed' else current
        rows = rows.annotate(matches_plan=Exists(plan_terms.filter(plan_id=segment['plan_id']))).filter(matches_plan=True)
    if segment.get('status'):
        rows = rows.annotate(current_term=Exists(current))
        if segment['status'] == 'lapsed':
            rows = rows.annotate(has_term=Exists(terms.filter(membership_id=OuterRef('pk'), ends_at__lte=now))).filter(has_term=True, current_term=False)
        else:
            rows = rows.filter(current_term=True)
    if segment.get('certification_id'):
        if not module_enabled(space, 'machines'):
            raise ValidationError({'certification_id': 'Machines are disabled.'})
        from apps.machines.models_certifications import CertificationGrant, CertificationType
        types = rbac.scope_notification_policy(CertificationType.objects.all(), makerspace_id=space.pk)
        if not types.filter(pk=segment['certification_id']).exists():
            raise ValidationError({'certification_id': 'Unknown certification in this makerspace.'})
        grants = rbac.scope_notification_policy(CertificationGrant.objects.all(), makerspace_id=space.pk,
                                               field='membership__makerspace_id').filter(
            membership_id=OuterRef('pk'), certification_type_id=segment['certification_id'], revoked_at__isnull=True,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        rows = rows.annotate(certified=Exists(grants)).filter(certified=True)
    return rows.order_by('pk')


@transaction.atomic
def send_broadcast(space, *, actor, title, body, **segment):
    from apps.makerspaces.guards import require_module_locked
    space = require_module_locked(space, 'membership')
    space = require_module_locked(space, 'notifications')
    if not rbac.can(actor, rbac.Action.MANAGE_MEMBERS, space):
        raise PermissionDenied()
    if not feature_enabled(space, 'membership.broadcasts'):
        raise ValidationError({'feature': 'Member broadcasts are disabled.'})
    # Explicit cap prevents one HTTP transaction from enqueueing an unbounded roster.
    ids = list(segment_members(space, segment).values_list('user_id', flat=True)[:2001])
    if len(ids) > 2000:
        raise ValidationError({'segment': 'Choose a segment of at most 2000 members.'})
    broadcast = MemberBroadcast.objects.create(makerspace=space, created_by=actor, title=title, body=body)
    audit.record(actor, 'notification.broadcast_created', makerspace=space, target=broadcast,
                 meta={'recipient_count': len(ids)})
    for user_id in ids:
        def build(uid=user_id):
            # Re-evaluate the segment after commit; revocation/opt-out always wins.
            space.refresh_from_db()
            if not feature_enabled(space, "membership.broadcasts"):
                return LifecyclePayload(text="", staff_channels_enabled=False)
            member = segment_members(space, segment).filter(user_id=uid).first()
            if member is None:
                return LifecyclePayload(text='', staff_channels_enabled=False)
            from apps.integrations.email_templates import render
            from apps.integrations.email_templates_registry_helpers import bag
            rendered = render(space, "membership", "requester", "broadcast", {
                "makerspace": bag(name=space.name), "announcement": bag(title=broadcast.title, body=broadcast.body),
            })
            return LifecyclePayload(
                text='', staff_channels_enabled=False,
                emails=(EmailDelivery(user_id=uid, to_email=member.user.email,
                                      subject=rendered["subject"], text_body=rendered["text_body"], html_body=rendered["html_body"],
                                      audience='requester', stream='membership', mute_event='broadcast'),),
                inbox=(InboxDelivery(uid, broadcast.title, broadcast.body, f'/m/{space.slug}/member'),),
            )
        notify_lifecycle(space, feature='members', event='broadcast', build=build)
    return broadcast, len(ids)
