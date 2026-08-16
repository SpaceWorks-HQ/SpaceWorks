from django.http import Http404

from apps.makerspaces.models import Makerspace
from apps.makerspaces.servability import servable_queryset


def get_public_makerspace(identifier):
    value = str(identifier or "").strip()
    if not value:
        raise Http404
    # Deterministic precedence: slug wins over public_code. Slugs are user-controlled
    # and could collide with another makerspace's 4-char code, so a single OR-query
    # could raise MultipleObjectsReturned (-> 500). Two scoped lookups avoid that.
    makerspace = (
        servable_queryset(Makerspace.objects.filter(slug=value)).first()
        or servable_queryset(Makerspace.objects.filter(
            public_code__iexact=value,
        )).first()
    )
    if makerspace is None:
        raise Http404
    return makerspace
