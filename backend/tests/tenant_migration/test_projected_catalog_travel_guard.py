"""Catalog-driven guard on the SHAPE of every model that travels.

The registry contracts next door prove a model is *classified*. They do not prove an
import can insert it. Two shapes break a move silently, and each was caught only by
running a full round-trip after the model had already shipped:

* a primary key the importer cannot reserve target values for -- both evidence
  retention models shipped with ``OneToOneField(primary_key=True)``, which exports no
  ``id`` column at all and raises ``UnsupportedPrimaryKey`` mid-move; and
* a deployment-global unique column with no collision rule, which violates its own
  constraint the first time a target deployment already holds the value.

Both checks enumerate ``PROJECTED_MODEL_LABELS``, so a newly projected model inherits
them instead of waiting for somebody to write it a bespoke round-trip test. Neither
touches the database -- this is model metadata only.
"""

from django.apps import apps

from apps.tenant_migration.pk_maps import unsupported_primary_key_reason
from apps.tenant_migration.tenant_dump_model_catalog import PROJECTED_MODEL_LABELS
from apps.tenant_migration.unique_values import DEPLOYMENT_GLOBAL_UNIQUE_RULES

# ``accounts.User`` is reconciled by ``identity_resolution.allocate_username``, which
# mints a fresh non-colliding username for every imported member. Its uniqueness is
# therefore resolved before insertion and deliberately carries no rule here. Anything
# else appearing in this set is an unhandled collision waiting for a real move.
UNIQUE_RESOLVED_BY_IDENTITY = {("accounts.User", "username")}


def test_every_projected_model_primary_key_is_importable():
    # The predicate comes from pk_maps itself, so this asserts what reservation
    # really requires. A type-only check here would accept a UUID primary key that
    # mints no default and still dies mid-move.
    unsupported = {}
    for label in sorted(PROJECTED_MODEL_LABELS):
        reason = unsupported_primary_key_reason(apps.get_model(label))
        if reason is not None:
            unsupported[label] = reason

    assert unsupported == {}, (
        "these models are projected but the importer cannot reserve their primary "
        "keys, so a tenant move raises UnsupportedPrimaryKey; prefer a normal auto "
        f"primary key plus a unique OneToOne: {unsupported}"
    )


def test_every_globally_unique_projected_column_has_a_collision_rule():
    unruled = set()
    for label in sorted(PROJECTED_MODEL_LABELS):
        for field in apps.get_model(label)._meta.get_fields():
            # Relational uniqueness is scoped by the row it points at, not by the
            # deployment, so a OneToOne cannot collide the way a bare column does.
            if field.is_relation or getattr(field, "primary_key", False):
                continue
            if not getattr(field, "unique", False):
                continue
            if (label, f"field:{field.name}") in DEPLOYMENT_GLOBAL_UNIQUE_RULES:
                continue
            unruled.add((label, field.name))

    assert unruled == UNIQUE_RESOLVED_BY_IDENTITY, (
        "every deployment-global unique column on a projected model needs a "
        "DEPLOYMENT_GLOBAL_UNIQUE_RULES entry deciding REGENERATE vs "
        "PRESERVE-and-refuse, or an explicit identity-resolution exemption; "
        f"unruled: {sorted(unruled - UNIQUE_RESOLVED_BY_IDENTITY)}, "
        f"stale exemptions: {sorted(UNIQUE_RESOLVED_BY_IDENTITY - unruled)}"
    )
