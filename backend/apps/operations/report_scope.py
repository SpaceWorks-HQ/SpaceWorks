from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


def eligible_makerspaces(*source_modules):
    queryset = servable_queryset(Makerspace.objects.filter(
        superadmin_access_enabled=True,
        enabled_modules__contains=["reports"],
    ))
    for module in source_modules:
        queryset = queryset.filter(enabled_modules__contains=[module])
    return queryset


def eligible_makerspace_ids(*source_modules):
    return list(eligible_makerspaces(*source_modules).values_list("id", flat=True))


def scoped_ids(makerspace_id, *source_modules):
    return [makerspace_id] if makerspace_id is not None else eligible_makerspace_ids(*source_modules)
