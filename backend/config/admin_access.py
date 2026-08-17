from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth import logout
from django.db import models
from django.http import HttpResponseForbidden
from django.urls import reverse

from config.admin_source_gate import AdminSourceGateMixin


# Models whose makerspace is reached via a nested relation (no direct `makerspace` FK).
# Keyed by "app_label.model_name" (lowercase) -> ORM lookup ending in _id.
NESTED_MAKERSPACE_LOOKUPS = {
    "accounts.memberclaimcode": "membership__makerspace_id",
    "accounts.oidcbrowserattempt": "intended_membership__makerspace_id",
    "makerspaces.membershiprequest": "makerspace_id",
    "makerspaces.makerspacewaiver": "makerspace_id",
    # Profiles hang off the membership, so the membership is the only end of the row
    # that names a tenant.
    "makerspaces.memberprofile": "membership__makerspace_id",
    "makerspaces.memberproject": "profile__membership__makerspace_id",
    "maintenance.maintenanceschedule": "machine__makerspace_id",
    "maintenance.maintenancelog": "machine__makerspace_id",
    "maintenance.maintenancelogdocument": "log__machine__makerspace_id",
    "hardware_requests.hardwarerequestitemasset": "asset__makerspace_id",
    "warranty.warrantydocument": "warranty__makerspace_id",
    "procurement.tobuyreceipt": "to_buy_item__makerspace_id",
    "machines.machineoperator": "machine__makerspace_id",
    "machines.machineusageentry": "machine__makerspace_id",
    "machines.machinedocument": "machine__makerspace_id",
    "machines.machineerrorlog": "machine__makerspace_id",
    "machines.machineconsumable": "machine__makerspace_id",
    "machines.servicebucket": "machine__makerspace_id",
    "machines.servicerequestconsumption": "service_request__makerspace_id",
    # Scoped through the ROLE, not the machine: a type link may point at a global
    # built-in type that belongs to no makerspace, so the role is the only end of the
    # row that always names a tenant.
    "machines.rolemachinetypescope": "role__makerspace_id",
    "machines.rolemachinescope": "role__makerspace_id",
    "bookings.booking": "space__makerspace_id",
    "presence.presencesession": "makerspace_id",
    "payments.makerspacepaymentsettings": "makerspace_id",
    "tenant_migration.disclosureclosureapproval": "makerspace_id",
    "tenant_migration.tenantmigrationexportjob": "export_job__makerspace_id",
}

# Registered admin models that are intentionally NOT makerspace-scoped (account/global).
GLOBAL_ADMIN_MODELS = {
    "accounts.user",
    "accounts.platformsocialauthsettings",
    # The login-method switches govern credentials, and credentials resolve before a
    # makerspace is selected — the same reason social auth is platform-scoped.
    "accounts.platformloginmethods",
    "accounts.passwordresetenvelope",
    "accounts.socialidentity",
    # Platform-scoped for the same reason as the built-in providers: identity resolves
    # before a makerspace is selected, so an OIDC provider cannot belong to one.
    "accounts.oidcprovider",
    "auth.group",
    "axes.accessattempt",
    "axes.accessfailurelog",
    "axes.accesslog",
    "integrations.platformemailsettings",
    "integrations.platformpushsettings",
    # Platform-scoped for the same reason identity is: a sign-in code is sent before any
    # makerspace has been selected, so there is no tenant to own the credentials.
    "integrations.platformsmssettings",
    "integrations.dailyotpsmscounter",
    "payments.platformstripeconnectsettings",
    "updates.platformupdatesettings",
    "backup.platformbackupsettings",
    "backup.backuparchive",
    "backup.restoreoperation",
    "backup.deploymentrecoverystate",
    "backup.backuplease",
    "backup.restorerollbackobject",
    "encryption.piiglobalwritefence",
    "token_blacklist.blacklistedtoken",
    "token_blacklist.outstandingtoken",
}


class AdminSuperuserOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        try:
            prefix = reverse("admin:index")
        except Exception:
            prefix = "/control/"
        self.admin_prefix = prefix if prefix.endswith("/") else f"{prefix}/"
        self.admin_root = self.admin_prefix.rstrip("/")
        try:
            self.admin_login_path = reverse("admin:login")
        except Exception:
            self.admin_login_path = f"{self.admin_prefix}login/"

    def __call__(self, request):
        if self._password_login_blocked(request):
            # `/control/login/` is Django's own AdminSite login, so `LoginView`'s check
            # never sees it. Refused BEFORE the form authenticates, so no session is
            # minted; existing sessions are left alone, because a login-method switch is a
            # policy change and not a revocation (phase 11 report, A2).
            #
            # This is enforced only while a superadmin can still get in another way -- see
            # `_password_login_blocked`. Social sign-in issues JWTs for the React console
            # and never creates a Django session, so blocking this unconditionally would
            # make the one page that can re-enable passwords permanently unreachable the
            # moment the last admin session expired.
            return HttpResponseForbidden(
                "Password sign-in is not available on this deployment."
            )
        if self._is_admin_path(request.path):
            user = getattr(request, "user", None)
            if getattr(user, "is_authenticated", False) and not self._has_access(user):
                # The admin login view authenticates before we can see the user, so an
                # is_staff non-superuser can mint a Django admin session. Flush it here so
                # the stray session can't linger (and the user isn't locked out of logout).
                # The React staff console uses JWT, not this session, so this is safe.
                logout(request)
                return HttpResponseForbidden()
        return self.get_response(request)

    def _is_admin_path(self, path):
        return path == self.admin_root or path.startswith(self.admin_prefix)

    def _password_login_blocked(self, request):
        """Whether this control-plane login must be refused.

        Two conditions, and the second is what stops the fix becoming the lockout:

        1. Password sign-in is switched off. (`password_login_enabled` fails OPEN, like
           every other capability read on an auth path.)
        2. `/control/` is reachable without a password at all — i.e. this deployment has
           a `PLATFORM_ADMIN_SSO` path. Today it does not: social sign-in mints JWTs for
           the React console and never a Django session, so with no second route the
           switch would seal the only page that can undo it. Until such a route exists,
           the control plane keeps its password door and the switch governs the
           application surfaces, which is what it is actually for.

        The consequence is stated rather than hidden: with `password_enabled=False` a
        superadmin can still sign in at `/control/`. That surface is superadmin-only,
        rate-limited by django-axes, and deliberately not proxied on the public frontend
        port, so it is the platform's break-glass entry — the same role Platform Email
        plays for the superadmin-access toggle.
        """
        if request.method != "POST" or request.path != self.admin_login_path:
            return False
        if not settings.PLATFORM_ADMIN_SSO:
            return False
        from apps.accounts.login_methods import password_login_enabled

        return not password_login_enabled()

    def _has_access(self, user):
        from apps.accounts.models import User

        return bool(
            user.is_active
            and user.is_superuser
            and getattr(user, "access_status", None) == User.AccessStatus.ACTIVE
            # The default super123 seed must rotate before reaching the admin too,
            # otherwise it could bypass the API/staff-console forced-change gate.
            and not getattr(user, "must_change_password", False)
        )


class AdminCspEvalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path_info == "/control" or request.path_info.startswith("/control/"):
            # Unfold's standard Alpine build requires unsafe-eval; the Django admin is
            # superuser-gated, so keep this exception scoped to admin responses only.
            merged = dict(getattr(response, "_csp_update", None) or {})
            script_src = merged.get("script-src", [])
            if isinstance(script_src, str):
                script_src = [script_src]
            else:
                script_src = list(script_src)
            if "'unsafe-eval'" not in script_src:
                script_src.append("'unsafe-eval'")
            merged["script-src"] = script_src

            endpoint = getattr(settings, "AWS_S3_PUBLIC_ENDPOINT_URL", "") or ""
            if endpoint:
                parts = urlsplit(endpoint)
                if parts.scheme and parts.netloc:
                    origin = f"{parts.scheme}://{parts.netloc}"
                    img_src = merged.get("img-src", [])
                    if isinstance(img_src, str):
                        img_src = [img_src]
                    else:
                        img_src = list(img_src)
                    if origin not in img_src:
                        img_src.append(origin)
                    merged["img-src"] = img_src

            response._csp_update = merged
        return response


class SuperuserOnlyModelAdmin(AdminSourceGateMixin):
    def resolve_hidden_lookup(self):
        from apps.makerspaces.models import Makerspace

        model = self.model
        model_key = f"{model._meta.app_label}.{model._meta.model_name}"
        if model_key in GLOBAL_ADMIN_MODELS:
            return None
        if model is Makerspace:
            return "id"

        for field in model._meta.get_fields():
            if (
                field.name == "makerspace"
                and isinstance(field, (models.ForeignKey, models.OneToOneField))
            ):
                return "makerspace_id"

        return NESTED_MAKERSPACE_LOOKUPS.get(model_key)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        lookup = self.resolve_hidden_lookup()
        if not lookup:
            return queryset

        from apps.makerspaces.models import Makerspace

        if self.model is Makerspace:
            # Governance visibility: a superadmin can see that a hidden
            # makerspace exists in the changelist only. Other admin contexts
            # such as object pages, autocomplete, and FK widgets stay scoped.
            url_name = getattr(getattr(request, "resolver_match", None), "url_name", "") or ""
            if url_name.endswith("_changelist"):
                return queryset

        from apps.accounts import rbac

        hidden = rbac.superadmin_hidden_makerspace_ids()
        if hidden:
            queryset = queryset.exclude(**{f"{lookup}__in": hidden})
        return queryset

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # A plain (non-autocomplete) FK ModelChoiceField builds its options from the
        # target model's default manager, NOT the target admin's get_queryset â€” so a
        # makerspace FK widget (e.g. ApiClient/ToBuyItem add/change forms) would still
        # list and let a superadmin target a hard-hidden makerspace. Scope every
        # makerspace FK widget to visible makerspaces to close that hard-hide bypass.
        from apps.makerspaces.models import Makerspace

        if (
            getattr(db_field, "remote_field", None) is not None
            and db_field.remote_field.model is Makerspace
            and "queryset" not in kwargs
        ):
            from apps.accounts import rbac

            queryset = Makerspace.objects.all()
            hidden = rbac.superadmin_hidden_makerspace_ids()
            if hidden:
                queryset = queryset.exclude(id__in=hidden)
            kwargs["queryset"] = queryset
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def _obj_in_hidden(self, obj):
        """True if `obj` belongs to a hard-hidden makerspace. Complements
        get_queryset (which only hides changelists) by blocking the object-level
        view/change/delete PAGES too, so /control/ can't reach a hidden row by id."""
        if obj is None:
            return False
        lookup = self.resolve_hidden_lookup()
        if not lookup:
            return False

        from apps.accounts import rbac

        hidden = rbac.superadmin_hidden_makerspace_ids()
        if not hidden:
            return False
        value = obj
        for part in lookup.split("__"):
            value = getattr(value, part, None)
            if value is None:
                return False
        return value in hidden

    def _has_superuser_access(self, request):
        from apps.accounts.models import User

        user = getattr(request, "user", None)
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and user.is_superuser
            and getattr(user, "access_status", None) == User.AccessStatus.ACTIVE
            and not getattr(user, "must_change_password", False)
        )

    def has_view_permission(self, request, obj=None):
        return self._has_superuser_access(request) and not self._obj_in_hidden(obj)

    def has_add_permission(self, request):
        return self._has_superuser_access(request)

    def has_change_permission(self, request, obj=None):
        return self._has_superuser_access(request) and not self._obj_in_hidden(obj)

    def has_delete_permission(self, request, obj=None):
        return self._has_superuser_access(request) and not self._obj_in_hidden(obj)

    def has_module_permission(self, request):
        return self._has_superuser_access(request)
