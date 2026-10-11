"""Use the reader's report action for manual reads, scheduled scope for internal work.

Hidden makerspaces remain readable by their own authorized staff. Applying background
fan-out eligibility to a manual read would silently erase those staff's report rows.
"""

from apps.accounts import rbac


def report_queryset(queryset, space_id, action, *, actor=None, field="makerspace_id"):
    if actor is None:
        return rbac.scope_for_scheduled_work(queryset, makerspace_id=space_id, field=field)
    return rbac.scope_by_action(actor, action, queryset, field=field).filter(**{field: space_id})
