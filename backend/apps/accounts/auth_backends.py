"""Django authentication backend with permanent Lane D stub refusal."""

from django.contrib.auth.backends import ModelBackend


class SpaceWorksModelBackend(ModelBackend):
    def user_can_authenticate(self, user):
        return bool(
            not getattr(user, "is_tenant_dump_stub", False)
            and super().user_can_authenticate(user)
        )
