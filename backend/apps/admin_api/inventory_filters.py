from django.db.models import F, Q

from apps.inventory.search import apply_q


def apply_inventory_list_filters(queryset, query_params):
    archived = query_params.get("archived")
    if archived in {"true", "false"}:
        queryset = queryset.filter(is_archived=(archived == "true"))
    q = (query_params.get("q") or "").strip()
    if q:
        # Full-text + trigram over the product's own columns (apps/inventory/search.py); the
        # category name is not in the vector, so it stays a plain match ORed in.
        matched = apply_q(queryset, q).values("pk")
        queryset = queryset.filter(Q(pk__in=matched) | Q(category__name__icontains=q))
    if query_params.get("low_stock") == "true":
        queryset = queryset.annotate(available_x5=F("available_quantity") * 5).filter(
            available_x5__lte=F("total_quantity")
        )
    return queryset
