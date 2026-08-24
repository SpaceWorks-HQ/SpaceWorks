import inspect

import pytest
from django.db import connection

from apps.tenant_migration.tenant_dump_catalog import validate_unowned_tables
from apps.tenant_migration.tenant_dump_verification import verify_projection_database


pytestmark = pytest.mark.django_db


def test_real_database_unowned_table_universe_matches_reviewed_catalog():
    validate_unowned_tables(connection.introspection.table_names())


@pytest.mark.xfail(strict=True, reason="SPEC BUG: backend/apps/tenant_migration/tenant_dump_verification.py:75-86 omits manifest-bound row-count, lost-edge, and semantic-reference inputs.")
def test_projection_verifier_accepts_exact_row_loss_and_semantic_expectations():
    parameters = inspect.signature(verify_projection_database).parameters

    assert {
        "expected_row_counts",
        "expected_cross_tenant_lost_edges",
        "expected_semantic_references",
    } <= set(parameters), (
        "Scratch and restored verification must independently reconcile row counts, "
        "lost edges, and semantic references against the manifest."
    )


def test_projection_verifier_pins_cache_emptiness_at_both_restore_boundaries():
    source = inspect.getsource(verify_projection_database)

    assert 'verify_tables_empty(using, {"spaceworks_cache"})' in source
    assert "verify_source_disposition_tables_empty(using)" in source
