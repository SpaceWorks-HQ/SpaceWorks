from django.apps import AppConfig
from django.db.models.signals import post_delete, post_save


class MakerspacesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.makerspaces"

    def ready(self):
        from django.db import transaction
        from django.utils import timezone

        from apps.makerspaces import domain_verification
        from apps.makerspaces.cors import register_signal
        from apps.makerspaces.hosting import invalidate
        from apps.makerspaces.models import Makerspace

        register_signal()
        self._register_separability()

        def invalidate_hosting_cache(**kwargs):
            # Any write to frontend_domain / frontend_domain_status must drop the
            # verified-domains cache on commit — unconditional so serializer save,
            # _commit_status, provision_subdomain, and /control/ edits are all covered.
            transaction.on_commit(invalidate)

        def reconcile_selfhost_domain(sender, instance, **kwargs):
            # Self-host: any saved makerspace with a non-empty but not-yet-VERIFIED
            # frontend_domain is trusted automatically (operator owns DNS + server).
            # Use .update() to avoid recursive save(); schedule an explicit invalidate
            # because .update() bypasses the post_save signal above.
            if not domain_verification.is_self_host():
                return
            if instance.frontend_domain and instance.frontend_domain_status != Makerspace.DomainStatus.VERIFIED:
                Makerspace.objects.filter(pk=instance.pk).update(
                    frontend_domain_status=Makerspace.DomainStatus.VERIFIED,
                    domain_verified_at=timezone.now(),
                )
                transaction.on_commit(invalidate)

        def ensure_default_roles_on_create(sender, instance, created, **kwargs):
            if not created:
                return
            from apps.makerspaces.roles import ensure_default_roles

            # Seed in the SAME transaction as the makerspace insert (not on_commit)
            # so a new makerspace is never observable without its five protected
            # defaults, and a seeding failure rolls the creation back.
            ensure_default_roles(instance)

        def ensure_pii_write_fence_on_create(sender, instance, created, **kwargs):
            if not created:
                return
            from apps.encryption.models import PiiMakerspaceWriteFence

            # Keep the persistent fail-closed row in the same transaction as the
            # tenant insert, just like default-role provisioning.
            PiiMakerspaceWriteFence.objects.get_or_create(makerspace=instance)

        post_save.connect(
            reconcile_selfhost_domain,
            sender=Makerspace,
            dispatch_uid="makerspaces.reconcile_selfhost_domain_on_save",
            weak=False,
        )
        post_save.connect(
            invalidate_hosting_cache,
            sender=Makerspace,
            dispatch_uid="makerspaces.invalidate_hosting_cache_on_save",
            weak=False,
        )
        post_save.connect(
            ensure_default_roles_on_create,
            sender=Makerspace,
            dispatch_uid="makerspaces.ensure_default_roles_on_create",
            weak=False,
        )
        post_save.connect(
            ensure_pii_write_fence_on_create,
            sender=Makerspace,
            dispatch_uid="makerspaces.ensure_pii_write_fence_on_create",
            weak=False,
        )
        post_delete.connect(
            invalidate_hosting_cache,
            sender=Makerspace,
            dispatch_uid="makerspaces.invalidate_hosting_cache_on_delete",
            weak=False,
        )

    def _register_separability(self):
        """Publish purge plans and the runtime-active manifest (plan B1/B2).

        The manifest exists because a tombstoned app stays in ``INSTALLED_APPS`` —
        it has to, or its historical migrations unapply — so ``apps.is_installed()``
        answers "are the tables there?" when the caller means "are the surfaces
        live?". ``apps/printing`` and ``apps/roadmap`` are the precedent: both are
        installed and both are tombstoned.

        Query-free and idempotent, as ready() requires.
        """
        from apps.makerspaces.module_purge_plans import PLANS
        from apps.separability.registry import (
            register_purge_plan,
            register_runtime_app,
            registered_purge_modules,
            runtime_active,
        )

        already = registered_purge_modules()
        for plan in PLANS:
            if plan.key not in already:
                register_purge_plan(plan.key, plan)

        # The two apps that are already tombstoned. Everything else defaults to
        # active, so no app has to opt in to keep working.
        for app_label in ("printing", "roadmap"):
            if runtime_active(app_label):
                register_runtime_app(app_label, tombstoned=True)
