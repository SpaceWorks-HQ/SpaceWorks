from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.admin_api.views_hosting import TlsCheckView
from apps.payments.views import StripeWebhookView
from apps.payments.views_connect import (
    StripeConnectCallbackView,
    StripeConnectWebhookView,
)
from apps.separability.registry import runtime_active


def separable(app_label, route, urlconf, **kwargs):
    """Routes for a separable app, spliced in place -- empty while it is tombstoned.

    Returns a list so call sites can `*`-unpack it and keep the entry at its original
    position: URL resolution is order-sensitive, and appending conditional routes at
    the end of the list would change which pattern wins.

    `include()` is called only when the app is active, deliberately. A tombstoned app
    may have had its views deleted (`apps/printing` and `apps/roadmap` are the
    precedent), and importing its urlconf to then discard it would crash on exactly
    the deployments this exists to support.
    """
    return [path(route, include(urlconf), **kwargs)] if runtime_active(app_label) else []


def docs_root(_request):
    return HttpResponse(
        """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Space Works API</title>
    <script>
      window.location.replace(window.location.hash ? "/redoc/" : "/docs/");
    </script>
    <noscript>
      <meta http-equiv="refresh" content="0; url=/docs/">
      <a href="/docs/">Open Swagger UI</a>
      <a href="/redoc/">Open Redoc</a>
    </noscript>
  </head>
  <body></body>
</html>""",
        content_type="text/html",
    )


urlpatterns = [
    path(
        "api/v1/webhooks/stripe/connect",
        StripeConnectWebhookView.as_view(),
        name="stripe-connect-webhook",
    ),
    path(
        "api/v1/payments/connect/callback",
        StripeConnectCallbackView.as_view(),
        name="stripe-connect-callback",
    ),
    path("api/v1/webhooks/stripe/<str:public_code>", StripeWebhookView.as_view(), name="stripe-webhook"),
    path('api/v1/', include('apps.machines.urls')),
    *separable("events", "api/v1/public/", "apps.events.urls_public"),
    *separable("bookings", "api/v1/public/", "apps.bookings.urls_public"),
    *separable("presence", "api/v1/public/", "apps.presence.urls"),
    path("api/v1/", include("apps.payments.urls")),
    path(
        "api/v1/internal/tls-check",
        TlsCheckView.as_view(),
        name="internal-tls-check",
    ),
    path("", docs_root, name="docs-root"),
    # Mounted at /control/ (not /admin/) so it never collides with the React staff
    # console, which owns /admin on the SPA. The Django admin is the Super Admin
    # control plane and lives on its own dedicated prefix.
    path("control/", admin.site.urls),
    path("api/", include("apps.inventory.urls")),          # existing, unchanged
    # Versioned alias of the public routes. Namespaced so it does NOT collide with the
    # unnamespaced names above â€” reverse("public-inventory") stays /api/public/...,
    # while /api/v1/public/... is reachable directly (and via "v1:public-inventory").
    path("api/v1/", include(("apps.inventory.urls", "inventory"), namespace="v1")),
    path("api/v1/", include("apps.makerspaces.urls")),
    path("api/v1/", include("apps.hardware_requests.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),   # staff auth surface
    path("api/v1/admin/", include("apps.admin_api.urls")),
    # Mounted at admin_api's own prefix so the paths and route names are unchanged by
    # the relocation, and *after* it so a relocated route can never shadow one that
    # stayed behind. Every warranty pattern is a distinct literal, so ordering is
    # belt-and-braces rather than load-bearing.
    *separable("warranty", "api/v1/admin/", "apps.warranty.urls"),
    *separable("maintenance", "api/v1/admin/", "apps.maintenance.urls"),
    *separable("presence", "api/v1/admin/", "apps.presence.urls_admin"),
    *separable("events", "api/v1/admin/", "apps.events.urls_admin"),
    *separable("bookings", "api/v1/admin/", "apps.bookings.urls_admin"),
    path("api/v1/admin/", include("apps.boxes.urls")),
    path("api/v1/admin/", include("apps.evidence.urls")),
    path("api/v1/", include("apps.operations.urls")),
    path("api/v1/integrations/", include("apps.integrations.urls")),
    *separable("procurement", "api/v1/procurement/", "apps.procurement.urls"),
    *separable("notifications", "api/v1/notifications/", "apps.notifications.urls"),
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="api-redoc-ui",
    ),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
]
