"""Explicit compatibility barrel for the email outbox and delivery boundary."""

from .dispatch_policy import EMAIL_MODULE_EXEMPT, email_module_blocks
from .dispatch_outbox import _create_email_log, _enqueue, dispatch_email
from .dispatch_delivery import _deliver
