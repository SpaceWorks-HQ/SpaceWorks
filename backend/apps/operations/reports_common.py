from django.db.models import QuerySet
from django.db.models.functions import TruncDay, TruncMonth

from apps.makerspaces.models import Makerspace
from apps.operations.report_scope import scoped_ids


def report_spaces(makerspace_id, *required_modules) -> QuerySet:
    return Makerspace.objects.filter(
        id__in=scoped_ids(makerspace_id, *required_modules)
    ).order_by("id")


def apply_range(queryset, field, date_range):
    if not date_range:
        return queryset
    start, end = date_range
    if start is not None:
        queryset = queryset.filter(**{f"{field}__gte": start})
    if end is not None:
        queryset = queryset.filter(**{f"{field}__lt": end})
    return queryset


def period_expression(field, grain):
    return TruncMonth(field) if grain == "month" else TruncDay(field)


def limited(records, limit):
    return records if limit is None else records[:limit]
