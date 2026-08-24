from copy import deepcopy

import pytest

from apps.backup.physical_catalog import catalog_difference, catalog_digest
from apps.backup.recipient_selection import BackupBuildError
from apps.backup.reservation_catalog import IndexComponent, UniqueRule
from apps.backup.source_verifier import _assert_catalog_reproduced


CONSTRAINT_SOURCE = (
    "CHECK (((channel)::text = ANY "
    "(ARRAY['tenant_email'::character varying, "
    "'operator_email'::character varying]::text[])))"
)
CONSTRAINT_ROUND_TRIP = (
    "CHECK (((channel)::text = ANY "
    "(ARRAY['tenant_email'::character varying::text, "
    "'operator_email'::character varying::text])))"
)
INDEX_SOURCE = (
    "CREATE UNIQUE INDEX uniq_probe ON public.probe USING btree (user_id) "
    "WHERE ((state)::text = ANY ((ARRAY['requested'::character varying, "
    "'invited'::character varying])::text[]))"
)
INDEX_ROUND_TRIP = (
    "CREATE UNIQUE INDEX uniq_probe ON public.probe USING btree (user_id) "
    "WHERE ((state)::text = ANY (ARRAY[('requested'::character varying)::text, "
    "('invited'::character varying)::text]))"
)


def _ledger(section, definition):
    if section == "constraints":
        row = [
            "public", "probe", "ck_probe", "c", False, False, True, definition
        ]
    else:
        row = [
            "public", "probe", "uniq_probe", True, False, True, False, definition
        ]
    return {section: [row]}


def _unique_rule(index_definition, predicate):
    component = IndexComponent(
        position=1,
        expression_sql="user_id",
        source_column="user_id",
        type_identity="pg_catalog.int8:bigint",
        operator_class="pg_catalog.int8_ops",
        collation="",
        collation_provider="",
        collation_deterministic=True,
        collation_locale="",
        collation_version="",
        collation_actual_version="",
    )
    return UniqueRule(
        schema="public",
        table="probe",
        index_name="uniq_probe",
        exact_index_definition=index_definition,
        exact_constraint_definition="",
        predicate_sql=predicate,
        nulls_not_distinct=False,
        deferrable=False,
        initially_deferred=False,
        primary=False,
        components=(component,),
    )


@pytest.mark.parametrize(
    ("section", "migration_definition", "round_trip_definition"),
    (
        ("constraints", CONSTRAINT_SOURCE, CONSTRAINT_ROUND_TRIP),
        ("indexes", INDEX_SOURCE, INDEX_ROUND_TRIP),
    ),
)
def test_catalog_digest_canonicalizes_only_the_proved_array_cast_round_trip(
    section, migration_definition, round_trip_definition
):
    source = _ledger(section, migration_definition)
    restored = _ledger(section, round_trip_definition)

    assert catalog_digest(source) == catalog_digest(restored)
    assert catalog_difference(source, restored) == []


def test_e7_unique_rule_identity_uses_the_same_catalog_canonicalizer():
    source_predicate = INDEX_SOURCE.split(" WHERE ", 1)[1]
    restored_predicate = INDEX_ROUND_TRIP.split(" WHERE ", 1)[1]
    source = _unique_rule(INDEX_SOURCE, source_predicate)
    restored = _unique_rule(INDEX_ROUND_TRIP, restored_predicate)

    assert source.definition_payload() == restored.definition_payload()
    assert source.identity == restored.identity


@pytest.mark.parametrize(
    "changed_definition",
    (
        INDEX_ROUND_TRIP.replace("'invited'", "'approved'"),
        INDEX_ROUND_TRIP.replace("(state)::text", "(phase)::text"),
        INDEX_ROUND_TRIP + " AND user_id IS NOT NULL",
    ),
)
def test_catalog_guard_refuses_genuine_predicate_changes(changed_definition):
    source = _ledger("indexes", INDEX_SOURCE)
    altered = _ledger("indexes", changed_definition)

    assert catalog_digest(source) != catalog_digest(altered)
    assert catalog_difference(source, altered)
    with pytest.raises(
        BackupBuildError,
        match="changed the physical catalog definition",
    ):
        _assert_catalog_reproduced(source, catalog_digest(source), altered)


def test_unproved_array_expression_rendering_stays_exact_and_refuses():
    source = _ledger(
        "indexes",
        INDEX_SOURCE.replace(
            "'requested'::character varying, 'invited'::character varying",
            "requested::character varying, invited::character varying",
        ),
    )
    altered = deepcopy(source)
    altered["indexes"][0][7] = altered["indexes"][0][7].replace(
        "(ARRAY[requested::character varying, invited::character varying])::text[]",
        "ARRAY[requested::character varying::text, invited::character varying::text]",
    )

    assert catalog_digest(source) != catalog_digest(altered)
    with pytest.raises(BackupBuildError):
        _assert_catalog_reproduced(source, catalog_digest(source), altered)
