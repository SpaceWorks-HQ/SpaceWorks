"""Drift guard holding the audit presentation catalogue exact against the source tree.

A new literal action without an entry, a permitted path no emitter writes, a request
reference that is not a declared HardwareRequest remap, or a dynamic call site the deny
policy does not cover all fail the build instead of silently changing disclosure.
"""

from apps.tenant_migration.audit_reference_guards import discover_audit_meta_references
from apps.tenant_migration.audit_references import (
    AUDIT_META_REFERENCES,
    AuditReferenceDisposition,
)

from .presentation_catalog import (
    DYNAMIC_EXACT_ACTIONS,
    LINK_RESOLVERS,
    NON_LITERAL_META_ACTIONS,
    PRESENTATION_CATALOG,
    WRAPPER_SITE_PREFIXES,
    is_denied,
)
from .presentation_discovery import discover_dynamic_audit_sites

REQUEST_MODEL = "hardware_requests.HardwareRequest"


def presentation_catalog_errors(*, discovery=None, sites=None):
    discovery = discovery or discover_audit_meta_references()
    sites = sites if sites is not None else discover_dynamic_audit_sites()
    errors = []
    exact = {action for site in sites if site.kind == "exact" for action in site.actions}
    non_literal = {
        action for site in sites if site.kind == "non_literal_meta" for action in site.actions
    }
    wrappers = {site.path for site in sites if site.kind == "wrapper"}
    if exact != set(DYNAMIC_EXACT_ACTIONS):
        errors.append(f"DYNAMIC_EXACT_ACTIONS drifted: {sorted(exact ^ DYNAMIC_EXACT_ACTIONS)}")
    if non_literal != set(NON_LITERAL_META_ACTIONS):
        errors.append(
            f"NON_LITERAL_META_ACTIONS drifted: {sorted(non_literal ^ NON_LITERAL_META_ACTIONS)}"
        )
    if wrappers != set(WRAPPER_SITE_PREFIXES):
        errors.append(
            f"WRAPPER_SITE_PREFIXES drifted: {sorted(wrappers ^ set(WRAPPER_SITE_PREFIXES))}"
        )
    known = discovery.actions | exact
    missing = discovery.actions - set(PRESENTATION_CATALOG)
    if missing:
        errors.append(f"literal audit actions without a catalogue entry: {sorted(missing)}")
    paths = {}
    for action, path in discovery.meta_paths:
        paths.setdefault(action, set()).add(path)
    for action, entry in PRESENTATION_CATALOG.items():
        if action not in known:
            errors.append(f"catalogue entry for an action nothing emits: {action}")
            continue
        declared = paths.get(action, set())
        for path in entry.permitted_meta_paths:
            if path not in declared:
                errors.append(f"{action}: permitted path {path!r} is not a literal emitted path")
            elif any(other.startswith(path + ".") for other in declared):
                errors.append(f"{action}: permitted path {path!r} is a parent, not a leaf")
        if is_denied(action) and entry.permitted_meta_paths:
            errors.append(f"{action}: denied by the dynamic policy but permits metadata")
        for path in entry.request_reference_paths:
            reference = AUDIT_META_REFERENCES.get((action, path))
            if (
                path not in entry.permitted_meta_paths
                or reference is None
                or reference.disposition is not AuditReferenceDisposition.REMAP
                or reference.target_model_label != REQUEST_MODEL
            ):
                errors.append(f"{action}: {path!r} is not a declared HardwareRequest reference")
        if entry.link_resolver is not None and entry.link_resolver not in LINK_RESOLVERS:
            errors.append(f"{action}: unknown link resolver {entry.link_resolver!r}")
    return errors
