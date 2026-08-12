from .views_email_templates_space import (
    EmailTemplateDetailView,
    EmailTemplateListView,
    EmailTemplatePreviewView,
    EmailTemplateResetView,
)
from .views_email_templates_types import (
    MachineTypeEmailTemplateDetailView,
    MachineTypeEmailTemplateResetView,
)

__all__ = [
    "EmailTemplateDetailView",
    "EmailTemplateListView",
    "EmailTemplatePreviewView",
    "EmailTemplateResetView",
    "MachineTypeEmailTemplateDetailView",
    "MachineTypeEmailTemplateResetView",
]
