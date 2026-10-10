"""Owner scope for borrowing data, including spaces with account-only borrowing."""


def scope_by_borrower(borrower, queryset, *, makerspace, owner_field="requester", field="makerspace_id"):
    from apps.accounts.models import User
    from apps.makerspaces.servability import is_servable

    if not (borrower and borrower.is_authenticated and borrower.is_active
            and not borrower.is_tenant_dump_stub
            and borrower.access_status == User.AccessStatus.ACTIVE and is_servable(makerspace)):
        return queryset.none()
    # Borrowers never get staff rows. Membership-module admission is a separate gate
    # at the workflow boundary; an account-only space still has owner-scoped loans.
    return queryset.filter(**{field: makerspace.pk, owner_field: borrower})
