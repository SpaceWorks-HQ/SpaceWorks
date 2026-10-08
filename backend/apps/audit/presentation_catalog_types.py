"""The frozen entry type of the audit presentation catalogue.

An entry is the reviewed answer to "what may a staff reader see of this action's
metadata?". It names exact LEAF paths only; the projector rebuilds nested objects from
those leaves and never hands back a parent object wholesale, so a key added to an emitter
later stays hidden until someone reviews it into the catalogue.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditPresentation:
    action: str
    label: str
    permitted_meta_paths: tuple[str, ...] = ()
    # Meta paths declared (in AUDIT_META_REFERENCES) as HardwareRequest references; the
    # request timeline joins an audit row to a request only through these.
    request_reference_paths: tuple[str, ...] = ()
    # Name in the closed resolver registry, never an import path. Phase 10 ships none.
    link_resolver: str | None = None


def P(action, label, paths=(), *, request_refs=(), resolver=None):
    return AuditPresentation(action, label, tuple(paths), tuple(request_refs), resolver)
