import json
from io import BytesIO

from apps.accounts.models_oidc import OidcProvider

ORIGIN = "http://localhost:5000"
REDIRECT_URI = f"{ORIGIN}/member"


class JsonResponse:
    def __init__(self, payload, *, status=200, headers=None):
        body = json.dumps(payload).encode()
        self.status_code = status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.raw = BytesIO(body)


def make_provider(**overrides):
    values = {
        "slug": "campus",
        "display_name": "Campus SSO",
        "issuer": "https://idp.example.test",
        "jwks_url": "https://idp.example.test/jwks",
        "client_id": "spaceworks-browser",
    }
    values.update(overrides)
    return OidcProvider.objects.create(**values)


def metadata(provider, **overrides):
    values = {
        "issuer": provider.issuer,
        "authorization_endpoint": f"{provider.issuer}/authorize",
        "token_endpoint": f"{provider.issuer}/token",
        "jwks_uri": provider.jwks_url,
    }
    values.update(overrides)
    return values


def start(client, *, email="", makerspace_slug=""):
    body = {"redirect_uri": REDIRECT_URI}
    if email:
        body["email"] = email
    if makerspace_slug:
        body["makerspace_slug"] = makerspace_slug
    return client.post(
        "/api/v1/auth/social/oidc/campus/authorize",
        body,
        format="json",
        HTTP_ORIGIN=ORIGIN,
    )
