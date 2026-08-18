"""Shared factories for the audit row-MAC test modules."""

from django.contrib.auth import get_user_model

from apps.accounts.models import User
from apps.makerspaces.models import Makerspace


def make_user(username):
    return get_user_model().objects.create_user(
        username=username,
        email=f"{username}@example.test",
        role=User.Role.SPACE_MANAGER,
    )


def make_space(slug):
    return Makerspace.objects.create(name=slug, slug=slug)
