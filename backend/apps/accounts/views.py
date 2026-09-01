"""Compatibility imports for the split account endpoint modules."""

from apps.accounts.views_password import (
    ChangePasswordView,
    ForgotPasswordView,
    ResetPasswordConfirmView,
)
from apps.accounts.views_session import LoginView, LogoutView, MeView, RefreshView

__all__ = [
    "ChangePasswordView",
    "ForgotPasswordView",
    "LoginView",
    "LogoutView",
    "MeView",
    "RefreshView",
    "ResetPasswordConfirmView",
]
