"""One search contract for every list endpoint: ``?q=`` over a Postgres search vector.

Three models carry a trigger-maintained ``search_vector`` column (``InventoryProduct``,
``machines.Machine``, ``events.Event``). The vector is built in Postgres, not in ``save()``,
so bulk import, admin edits and raw SQL all keep it fresh, and it is a **derived** column:
omitted from data export and rebuilt by the trigger after a tenant move.

``apply_q`` combines a websearch-style full-text match (``"exact phrase"``, ``-excluded``)
with trigram similarity on the primary label, so a typo still finds the tool. Rows are
ordered by rank when a query is present; callers apply their own default ordering otherwise.

Never index a scoped-PII column. The trigger SQL below names plain columns only, and the
encrypted requester fields on ``HardwareRequest`` are deliberately not part of this contract
(that queue keeps its blind-index search in ``hardware_requests/queue_views.py``).

``apps/encryption/search.py`` is a different thing — blind-index lookups over encrypted
fields — and is not related to this module.
"""
import re

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramSimilarity
from django.db.models import F, Q, Value

SEARCH_CONFIG = "simple"  # language-neutral until phase 8 adds per-makerspace locales
TRIGRAM_THRESHOLD = 0.3
MAX_QUERY_LENGTH = 200


def clean_query(raw):
    text = (raw or "").strip()
    return text[:MAX_QUERY_LENGTH]


def _operators_present(query):
    lowered = f" {query.lower()} "
    return '"' in query or " -" in lowered or query.startswith("-") or " or " in lowered


def search_query(query):
    """Plain words match as prefixes (``solder`` finds ``soldering``, like the old substring
    search did); anything using quotes, ``-word`` or ``OR`` gets websearch semantics instead."""
    if _operators_present(query):
        return SearchQuery(query, search_type="websearch", config=SEARCH_CONFIG)
    terms = re.findall(r"\w+", query)
    if not terms:
        return SearchQuery(query, search_type="plain", config=SEARCH_CONFIG)
    return SearchQuery(" & ".join(f"{term}:*" for term in terms), search_type="raw", config=SEARCH_CONFIG)


def apply_q(queryset, raw_query, *, label_field="name", vector_field="search_vector"):
    """Filter ``queryset`` by ``raw_query``; unchanged (and unordered) when the query is blank."""
    query = clean_query(raw_query)
    if not query:
        return queryset
    search = search_query(query)
    similarity = TrigramSimilarity(label_field, Value(query))
    return (
        queryset.annotate(
            _rank=SearchRank(F(vector_field), search),
            _similarity=similarity,
        )
        .filter(Q(**{vector_field: search}) | Q(_similarity__gte=TRIGRAM_THRESHOLD))
        .order_by("-_rank", "-_similarity", label_field, "pk")
    )


def vector_trigger_sql(table, columns, *, trigger_name):
    """Forward/reverse SQL for a BEFORE INSERT OR UPDATE trigger that fills ``search_vector``.

    ``columns`` is an ordered list of (column, weight) pairs; weight A outranks D.
    """
    parts = " || ".join(
        f"setweight(to_tsvector('{SEARCH_CONFIG}', coalesce(NEW.{column}, '')), '{weight}')"
        for column, weight in columns
    )
    function = f"{trigger_name}_fn"
    forward = f"""
CREATE OR REPLACE FUNCTION {function}() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := {parts};
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS {trigger_name} ON {table};
CREATE TRIGGER {trigger_name}
  BEFORE INSERT OR UPDATE ON {table}
  FOR EACH ROW EXECUTE FUNCTION {function}();
UPDATE {table} SET search_vector = {parts.replace('NEW.', '')};
"""
    reverse = f"""
DROP TRIGGER IF EXISTS {trigger_name} ON {table};
DROP FUNCTION IF EXISTS {function}();
"""
    return forward, reverse
