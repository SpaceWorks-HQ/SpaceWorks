"""Declarative tenant-export contract and bounded archive execution.

The registries resolve Django models, so package import must stay lazy while Django is
still constructing the application registry.
"""

from .types import Fidelity

REGISTRY_VERSION = "2026-08-16.phase4.f1"

__all__ = (
    "DATASETS",
    "FIELDS",
    "MODELS",
    "SEMANTIC_REFERENCES",
    "TRAVERSALS",
    "USER_EDGES",
    "Fidelity",
    "REGISTRY_VERSION",
)


def __getattr__(name):
    if name == "DATASETS":
        from .datasets import DATASETS
        return DATASETS
    if name == "FIELDS":
        from .fields import FIELDS
        return FIELDS
    if name == "MODELS":
        from .models import MODELS
        return MODELS
    if name in {"SEMANTIC_REFERENCES", "USER_EDGES"}:
        from .references import SEMANTIC_REFERENCES, USER_EDGES
        return {"SEMANTIC_REFERENCES": SEMANTIC_REFERENCES, "USER_EDGES": USER_EDGES}[name]
    if name == "TRAVERSALS":
        from .traversals import TRAVERSALS
        return TRAVERSALS
    raise AttributeError(name)
