"""Exact PII-free manifest validation for the D6 user closure."""

from apps.data_export.references import USER_EDGES
from apps.data_export.types import Fidelity

from .tenant_dump_errors import TenantDumpClosureRefused
from .tenant_dump_user_closure import _closure, _edge_key, user_ref


def verify_user_closure_manifest(value, capture_id):
    if not isinstance(value, dict) or set(value) != {
        "included", "stubbed", "refused", "sha256"
    }:
        raise _invalid("The user closure manifest schema is invalid.")
    lists = {name: value[name] for name in ("included", "stubbed", "refused")}
    expected_keys = {
        "user_ref", "emitted_user_pk", "reason_code",
        "stub_schema_version", "referencing_edges",
    }
    edge_keys = {"model_label", "source_row_pk", "field_name"}
    seen_refs = set()
    seen_pks = set()
    allowed_edges = {
        (label, field_name)
        for (fidelity, label, field_name), edge in USER_EDGES.items()
        if fidelity is Fidelity.PORTABLE and edge.included
    }
    for disposition, entries in lists.items():
        if not isinstance(entries, list) or any(
            not isinstance(item, dict) for item in entries
        ):
            raise _invalid("A user closure disposition list is invalid.")
        if entries != sorted(entries, key=lambda item: item.get("user_ref", "")):
            raise TenantDumpClosureRefused(
                "A user closure disposition is not sorted.",
                reason_code="closure_manifest_unsorted",
            )
        for item in entries:
            if not isinstance(item, dict) or set(item) != expected_keys:
                raise _invalid("A user closure entry has an invalid schema.")
            pk = item["emitted_user_pk"]
            ref = item["user_ref"]
            valid_disposition = (
                disposition == "included"
                and item["reason_code"] == "tenant_exclusive"
                and item["stub_schema_version"] is None
            ) or (
                disposition == "stubbed"
                and item["reason_code"] == "not_tenant_exclusive"
                and item["stub_schema_version"] == 1
            ) or disposition == "refused"
            if (
                type(pk) is not int
                or pk <= 0
                or ref in seen_refs
                or pk in seen_pks
                or not valid_disposition
                or ref != user_ref(capture_id, pk)
            ):
                raise TenantDumpClosureRefused(
                    "A user closure identity/disposition is invalid.",
                    reason_code="closure_identity_invalid",
                )
            seen_refs.add(ref)
            seen_pks.add(pk)
            edges = item["referencing_edges"]
            if (
                not isinstance(edges, list)
                or any(not isinstance(edge, dict) or set(edge) != edge_keys for edge in edges)
                or any(
                    (edge["model_label"], edge["field_name"]) not in allowed_edges
                    or type(edge["source_row_pk"]) is not int
                    or edge["source_row_pk"] <= 0
                    for edge in edges
                )
                or len(
                    {
                        _manifest_edge_key(edge)
                        for edge in edges
                    }
                ) != len(edges)
                or edges != sorted(edges, key=_manifest_edge_key)
            ):
                raise _invalid("A user closure edge list is invalid.")
    actual = _closure(lists["included"], lists["stubbed"], lists["refused"])
    if actual.digest != value["sha256"]:
        raise TenantDumpClosureRefused(
            "The user closure manifest digest is invalid.",
            reason_code="closure_digest_mismatch",
        )
    if lists["refused"]:
        raise TenantDumpClosureRefused(
            "A refused user closure cannot be published.",
            reason_code="closure_contains_refusal",
            closure=actual,
        )
    return actual.digest


def _manifest_edge_key(edge):
    return _edge_key(
        (edge["model_label"], edge["source_row_pk"], edge["field_name"])
    )


def _invalid(detail):
    return TenantDumpClosureRefused(
        detail, reason_code="closure_manifest_invalid"
    )
