"""Source event codes are omitted and imported history cannot grant admission."""

import pytest

from apps.tenant_migration.omitted_fields import DERIVED, OMITTED_FIELD_RECONSTRUCTIONS
from apps.tenant_migration.target_projection import TARGET_FIELD_PROJECTION
from apps.tenant_migration.unique_values import DEPLOYMENT_GLOBAL_UNIQUE_RULES, REMAP


@pytest.mark.parametrize("label,constraint", [
    ("events.EventInvite", "event_invite_unique_code"),
    ("events.EventPromoCode", "event_promo_unique_code"),
])
def test_event_code_reconstruction_replaces_credentials_and_revokes_history(label, constraint):
    assert OMITTED_FIELD_RECONSTRUCTIONS[(label, "code_digest")] is DERIVED
    digest = TARGET_FIELD_PROJECTION[(label, "code_digest")]
    assert digest.resolved_value(label, "code_digest") != digest.resolved_value(label, "code_digest")
    assert TARGET_FIELD_PROJECTION[(label, "revoked_at")].resolved_value(label, "revoked_at")
    assert DEPLOYMENT_GLOBAL_UNIQUE_RULES[(label, constraint)].disposition is REMAP


def test_source_keyed_email_digest_is_cleared():
    label = "events.EventInvite"
    assert OMITTED_FIELD_RECONSTRUCTIONS[(label, "email_digest")] is DERIVED
    assert TARGET_FIELD_PROJECTION[(label, "email_digest")].resolved_value(label, "email_digest") == ""
