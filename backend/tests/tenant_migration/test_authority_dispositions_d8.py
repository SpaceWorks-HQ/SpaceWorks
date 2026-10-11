"""Literal authority disposition checks; expectations live in domain siblings."""

import pytest

from apps.tenant_migration.tenant_dump_authority import AUTHORITY_FIELD_OVERRIDES
from apps.tenant_migration.tenant_dump_catalog import FIELD_POLICIES
from apps.tenant_migration.tenant_dump_types import AuthorityDisposition as D
from .authority_expectations_d8 import EXPECTED


@pytest.mark.parametrize("edge, expected", EXPECTED.items())
def test_every_section_3a_field_has_its_exact_literal_disposition(edge, expected):
    assert FIELD_POLICIES[edge].dispositions == expected


def test_literal_section_3a_matrix_covers_every_authority_override_exactly_once():
    assert set(EXPECTED) == set(AUTHORITY_FIELD_OVERRIDES)


@pytest.mark.parametrize(
    "model_label",
    (
        "accounts.NativeAppRegistration",
        "apiclients.ApiClient",
        "integrations.EmailNotificationMute",
        "integrations.NotificationPreference",
        "integrations.NotificationRecipient",
        "integrations.RecipientCategoryScope",
        "integrations.RecipientMachineScope",
        "integrations.RecipientMachineTypeScope",
        "machines.RoleMachineScope",
        "machines.RoleMachineTypeScope",
        "makerspaces.MakerspaceRole",
        "makerspaces.SubdomainRequest",
        "organizations.Organization",
        "organizations.OrganizationMakerspace",
        "organizations.OrganizationMembership",
        "events.EventOrganizer",
    ),
)
def test_every_section_3a_drop_row_has_only_drop_field_dispositions(model_label):
    rules = [
        rule for (label, _field), rule in FIELD_POLICIES.items() if label == model_label
    ]
    assert rules
    assert all(rule.dispositions == (D.DROP,) for rule in rules)
