"""The audit presentation catalogue is exact, and its projector fails closed."""

from types import SimpleNamespace

import pytest

from apps.audit import presentation
from apps.audit.presentation_catalog import (
    DENIED_ACTION_PREFIXES,
    PRESENTATION_CATALOG,
    UNRECOGNIZED_LABEL,
    _compose,
    is_denied,
)
from apps.audit.presentation_catalog_types import P
from apps.audit.presentation_discovery import DynamicAuditSite
from apps.audit.presentation_guards import presentation_catalog_errors
from apps.tenant_migration.audit_reference_guards import (
    AuditMetaDiscovery,
    discover_audit_meta_references,
)


def test_catalogue_matches_the_source_tree_exactly():
    assert presentation_catalog_errors() == []


def test_every_discovered_literal_action_has_exactly_one_entry():
    discovered = discover_audit_meta_references().actions
    assert discovered <= set(PRESENTATION_CATALOG)


def test_duplicate_entries_are_refused():
    with pytest.raises(ValueError, match="Duplicate"):
        _compose((P("x.y", "X"),), (P("x.y", "Other"),))


def _discovery(actions, paths):
    return AuditMetaDiscovery(frozenset(actions), frozenset(paths), frozenset(), ())


def test_guard_reports_an_unreviewed_action_and_an_unknown_path(monkeypatch):
    discovery = _discovery({"request.accepted", "brand.new_action"}, {("request.accepted", "x")})
    errors = presentation_catalog_errors(discovery=discovery, sites=[])
    assert any("brand.new_action" in error for error in errors)
    # `accepted` is permitted for request.accepted but this discovery no longer emits it.
    assert any("'accepted' is not a literal emitted path" in error for error in errors)


def test_guard_reports_an_uncovered_dynamic_wrapper_site():
    sites = [DynamicAuditSite("new_app/services.py", "wrapper", frozenset())]
    errors = presentation_catalog_errors(sites=sites)
    assert any("WRAPPER_SITE_PREFIXES drifted" in error for error in errors)


def _row(action, meta):
    return SimpleNamespace(action=action, meta=meta)


def test_unknown_action_exposes_nothing():
    projection = presentation.project(_row("never.heard_of", {"email": "a@b.c"}))
    assert projection.action_label == UNRECOGNIZED_LABEL
    assert projection.meta == {}
    assert projection.meta_redacted is True
    assert projection.target_link is None


def test_unknown_action_with_empty_meta_is_still_marked_redacted():
    assert presentation.project(_row("never.heard_of", {})).meta_redacted is True


def test_denied_dynamic_namespace_forces_empty_meta_even_with_a_label():
    action = "qr.tool_created"  # an `a if x else b` dynamic emitter
    assert is_denied(action)
    projection = presentation.project(_row(action, {"qr_id": 4}))
    assert projection.meta == {} and projection.meta_redacted is True
    assert projection.action_label == PRESENTATION_CATALOG[action].label


def test_wrapper_prefix_denies_strings_no_literal_emitter_wrote():
    assert "auth." in DENIED_ACTION_PREFIXES
    assert presentation.project(_row("auth.social_login_failed", {"provider": "x"})).meta == {}


def test_non_literal_meta_action_is_denied():
    assert is_denied("makerspace.purged")
    assert presentation.project_meta("makerspace.purged", {"slug": "x"}) == ({}, True)


def test_only_permitted_leaves_survive_and_redaction_is_reported():
    entry = PRESENTATION_CATALOG["request.issued"]
    assert set(entry.permitted_meta_paths) == {"box_id", "evidence_id"}
    meta, redacted = presentation.project_meta(
        "request.issued", {"box_id": 3, "evidence_id": 9, "free_text": "secret"}
    )
    assert meta == {"box_id": 3, "evidence_id": 9}
    assert redacted is True
    assert presentation.project_meta("request.issued", {"box_id": 3}) == ({"box_id": 3}, False)


def test_a_dict_where_a_leaf_was_declared_is_withheld():
    meta, redacted = presentation.project_meta(
        "request.issued", {"box_id": {"nested": "surprise"}, "evidence_id": 1}
    )
    assert meta == {"evidence_id": 1} and redacted is True


def test_nested_leaves_are_rebuilt_without_their_parent_wholesale(monkeypatch):
    catalogue = {**PRESENTATION_CATALOG, "x.nested": P("x.nested", "Nested", ("a.b",))}
    monkeypatch.setattr(presentation, "PRESENTATION_CATALOG", catalogue)
    meta, redacted = presentation.project_meta(
        "x.nested", {"a": {"b": 1, "unreviewed_sibling": "hidden"}, "c": 2}
    )
    assert meta == {"a": {"b": 1}}
    assert redacted is True


def test_no_entry_permits_a_personal_or_free_text_key():
    forbidden = {"email", "phone", "username", "first_name", "last_name", "notes",
                 "reason", "name", "object_key", "redemption_ip", "card_number"}
    leaking = [
        (action, path)
        for action, entry in PRESENTATION_CATALOG.items()
        for path in entry.permitted_meta_paths
        if set(path.split(".")) & forbidden
    ]
    assert leaking == []


def test_request_reference_paths_are_declared_request_remaps():
    entry = PRESENTATION_CATALOG["box.scanned"]
    assert entry.request_reference_paths == ("request_id",)
    assert presentation.request_reference_paths("box.scanned") == ("request_id",)
    assert presentation.request_reference_paths("never.heard_of") == ()


def test_phase_ten_ships_no_target_links():
    assert all(entry.link_resolver is None for entry in PRESENTATION_CATALOG.values())
