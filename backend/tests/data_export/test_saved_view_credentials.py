"""UI preferences travel as data without bypassing the credential-name screen."""

import pytest

from apps.data_export.guards import RegistryError
from apps.data_export.guards_credentials import validate_credentials
from apps.data_export.types import Emitted, Fidelity


def test_saved_view_state_is_reviewed_data_for_both_fidelities():
    validate_credentials({
        (fidelity, "operations.SavedView", "state"): Emitted()
        for fidelity in Fidelity
    })


def test_a_new_credential_field_still_requires_an_explicit_decision():
    with pytest.raises(RegistryError, match="credential-like field not omitted"):
        validate_credentials({
            (Fidelity.PORTABLE, "operations.SavedView", "secret"): Emitted(),
        })
