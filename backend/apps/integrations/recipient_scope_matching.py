"""Pure subject matching for notification-recipient scope links."""


def rule_covers(row, scope) -> bool:
    """Whether a recipient row's narrowing admits this alert's subject.

    No links means everything, while a narrowed rule cannot cover an alert that names
    no subject. This is delivery configuration, so its open default is intentionally
    opposite to fail-closed role authority.
    """
    machine_ids = {link.machine_id for link in row.machine_scopes.all()}
    type_ids = {link.machine_type_id for link in row.machine_type_scopes.all()}
    category_ids = {link.category_id for link in row.category_scopes.all()}
    if not (machine_ids or type_ids or category_ids):
        return True
    if scope is None:
        return False
    return (
        (scope.machine_id is not None and scope.machine_id in machine_ids)
        or (scope.machine_type_id is not None and scope.machine_type_id in type_ids)
        or (scope.category_id is not None and scope.category_id in category_ids)
    )
