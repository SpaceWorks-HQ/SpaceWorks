"""Admin candidate adapter.  Mapped fields never reach Django's SQL SearchFilter."""

from django.conf import settings
from apps.encryption.search import indexed_candidates, verified_ids


class ScopedPiiAdminSearchMixin:
    """Opt-in admin configuration for one registry-approved source relation.

    ``pii_search_relation`` is empty for the source model itself and otherwise is
    the model relation path from the admin queryset to that source.
    """
    pii_search_model = None
    pii_search_relation = ""
    pii_search_fields = ()

    def get_search_results(self, request, queryset, search_term):
        enabled = settings.PII_ENCRYPTION_ENABLED
        original = self.search_fields
        if enabled:
            # Mapped fields must never reach Django's SQL SearchFilter over ciphertext.
            self.search_fields = tuple(field for field in original if field not in self.pii_search_fields)
        else:
            # Plaintext default deployment: preserve pre-encryption admin search by
            # letting the ORM search the mapped columns at their relation path.
            self.search_fields = tuple(original) + tuple(
                f"{self.pii_search_relation}{name}" for name in self.pii_search_fields
            )
        try:
            queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        finally:
            self.search_fields = original
        if not enabled or not search_term or not self.pii_search_model:
            return queryset, may_have_duplicates
        source = self.model
        if self.pii_search_relation:
            for relation in self.pii_search_relation.rstrip("__").split("__"):
                source = source._meta.get_field(relation).related_model
        ids = set()
        # Admin is superadmin-only; source candidates are still partitioned by the
        # source's own persisted makerspace rather than queried globally.
        from rest_framework.exceptions import ValidationError

        from apps.encryption.registry import fields_for_label
        from apps.encryption.search import legacy_plaintext_candidates
        dual_read = settings.PII_ENCRYPTION_DUAL_READ
        for field in fields_for_label(self.pii_search_model):
            if field.field_name not in self.pii_search_fields:
                continue
            exact = field.index_kind == "bloom_exact"
            path = (field.makerspace_path or "makerspace").replace(".", "__")
            if path.endswith("_id"):
                path = path[:-3]
            spaces = source.objects.values_list(path, flat=True).distinct()
            for makerspace_id in spaces:
                if not makerspace_id:
                    continue
                try:
                    candidate_ids = indexed_candidates(
                        makerspace_id=makerspace_id, model_label=self.pii_search_model,
                        field_name=field.field_name, term=search_term, exact=exact,
                    )
                except ValidationError:
                    candidate_ids = []
                candidate_rows = source.objects.filter(pk__in=candidate_ids)
                ids.update(verified_ids(candidate_rows, field_name=field.field_name, term=search_term, exact=exact))
            # Pre-backfill rows have no index during the dual-read rollout window.
            if dual_read:
                ids.update(legacy_plaintext_candidates(source.objects.all(), field_name=field.field_name, term=search_term, exact=exact))
        if ids:
            key = f"{self.pii_search_relation}pk__in" if self.pii_search_relation else "pk__in"
            queryset = queryset | self.get_queryset(request).filter(**{key: ids})
            may_have_duplicates = bool(self.pii_search_relation)
        return queryset, may_have_duplicates
