"""Compatibility imports for the split source-gate policy catalogs."""

from .gate_policy_http import (
    HTTP_EXEMPTIONS,
    HTTP_ANONYMOUS_EXEMPTIONS,
    HTTP_ANONYMOUS_PARTICIPANTS,
    ADMIN_ACTION_EXEMPTIONS,
)
from .gate_policy_tasks import (
    TASK_EXEMPTIONS,
    TASK_TENANT_RESOLVERS,
    TASK_INTERNAL_PARTICIPANTS,
    FANOUT_GATE_PARTICIPANTS,
)
from .gate_policy_objects import (
    LIFECYCLE_EXEMPTIONS,
    OBJECT_MUTATION_PARTICIPANTS,
)
