"""The single projector from a stored ``AuditLog`` row to what staff may see.

The staff audit list, the request timeline and the audit-trail CSV all call this, so
there is no second path that can hand ``row.meta`` to a reader. It fails closed:

- an action absent from the catalogue gets a fixed "unrecognized" label and ``{}``;
- an action under the dynamic deny policy gets ``{}`` (its label may still be shown);
- otherwise only the catalogue's exact LEAF paths are rebuilt, and only when the stored
  value is a scalar or a flat list of scalars -- a dict where a leaf was declared means
  the emitter changed shape, so it is withheld rather than passed through.

``meta_redacted`` is true whenever anything stored was not returned.
"""

from dataclasses import dataclass

from .presentation_catalog import (
    LINK_RESOLVERS,
    PRESENTATION_CATALOG,
    UNRECOGNIZED_LABEL,
    is_denied,
)

_MISSING = object()
_SCALARS = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class AuditProjection:
    action_label: str
    meta: dict
    meta_redacted: bool
    target_link: dict | None


def _lookup(meta, path):
    value = meta
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _presentable(value):
    if isinstance(value, _SCALARS):
        return True
    return isinstance(value, list) and all(isinstance(item, _SCALARS) for item in value)


def _insert(target, path, value):
    *parents, leaf = path.split(".")
    for part in parents:
        target = target.setdefault(part, {})
    target[leaf] = value


def _leaf_count(value):
    if isinstance(value, dict):
        return sum(_leaf_count(item) for item in value.values()) if value else 1
    return 1


def project_meta(action, meta):
    """Return ``(projected_meta, redacted)`` for one action and its stored metadata."""
    stored = meta if isinstance(meta, dict) else {}
    entry = PRESENTATION_CATALOG.get(action)
    if entry is None or is_denied(action):
        return {}, bool(stored) or entry is None
    projected, kept = {}, 0
    for path in entry.permitted_meta_paths:
        value = _lookup(stored, path)
        if value is _MISSING or not _presentable(value):
            continue
        _insert(projected, path, value)
        kept += 1
    return projected, kept < _leaf_count(stored) if stored else False


def target_link(row):
    entry = PRESENTATION_CATALOG.get(row.action)
    if entry is None or entry.link_resolver is None or is_denied(row.action):
        return None
    resolver = LINK_RESOLVERS.get(entry.link_resolver)
    return resolver(row) if resolver is not None else None


def action_label(action):
    entry = PRESENTATION_CATALOG.get(action)
    return entry.label if entry is not None else UNRECOGNIZED_LABEL


def project(row):
    meta, redacted = project_meta(row.action, row.meta)
    return AuditProjection(action_label(row.action), meta, redacted, target_link(row))


def request_reference_paths(action):
    """Declared HardwareRequest meta references for ``action`` (empty when denied)."""
    entry = PRESENTATION_CATALOG.get(action)
    if entry is None or is_denied(action):
        return ()
    return entry.request_reference_paths
