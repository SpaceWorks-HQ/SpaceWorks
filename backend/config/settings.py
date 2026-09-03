from datetime import timedelta
from pathlib import Path
import sys

from celery.schedules import crontab
import environ
from corsheaders.defaults import default_headers
from django.core.exceptions import ImproperlyConfigured

from config.storage_validation import assert_distinct_storage_buckets

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")
# Imported after read_env: both read TOMBSTONED_APPS straight from the environment,
# and the sidebar in config.unfold is built at import time.
from apps.separability.tombstones import tombstoned_app_labels
from config.unfold import UNFOLD

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

_configured_trusted_proxy_count = env.int("TRUSTED_PROXY_COUNT", default=None)
if not DEBUG and _configured_trusted_proxy_count is None:
    raise ImproperlyConfigured(
        "TRUSTED_PROXY_COUNT must be explicitly set when DEBUG is False. "
        "Use 0 for direct access or the exact number of trusted reverse proxies."
    )
if _configured_trusted_proxy_count is not None and _configured_trusted_proxy_count < 0:
    raise ImproperlyConfigured("TRUSTED_PROXY_COUNT cannot be negative.")
# Direct development access has no trusted proxy. Production may never reach this
# fallback because the guard above forces its topology to be declared explicitly.
TRUSTED_PROXY_COUNT = (
    0 if _configured_trusted_proxy_count is None else _configured_trusted_proxy_count
)


def normalize_platform_domain_suffix(raw):
    """Canonicalize the platform suffix to the leading-dot lowercase form.

    Blank/whitespace/None => "" (self-host). Otherwise lowercase + strip and
    prepend a leading "." if missing, so an operator may set PLATFORM_DOMAIN_SUFFIX
    as either "space-works.tech" or ".space-works.tech" and the stored value is always ".space-works.tech".
    The leading dot is what makes endswith(suffix) reject look-alikes (evilspace-works.tech)
    and what provisioning.provision_subdomain requires.
    """
    value = str(raw or "").strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else "." + value


PLATFORM_DOMAIN_SUFFIX = normalize_platform_domain_suffix(
    env("PLATFORM_DOMAIN_SUFFIX", default="")
)
INFRA_HOSTS = set(
    env.list(
        "INFRA_HOSTS",
        default=["localhost", "127.0.0.1", "backend", "backend:8000"],
    )
)
PLATFORM_STAFF_ORIGINS = env.list("PLATFORM_STAFF_ORIGINS", default=[])
BEHIND_TRUSTED_PROXY = env.bool("BEHIND_TRUSTED_PROXY", default=False)
PLATFORM_ORIGIN_HOST = env("PLATFORM_ORIGIN_HOST", default="")  # e.g. origin.space-works.tech; blank => resolution gate dormant
DOMAIN_CHANGE_COOLDOWN_SECONDS = env.int("DOMAIN_CHANGE_COOLDOWN_SECONDS", default=0)  # 0 => no cooldown
if BEHIND_TRUSTED_PROXY:
    ALLOWED_HOSTS = ["*"]
PUBLIC_APP_BASE_URL = env("PUBLIC_APP_BASE_URL", default="").rstrip("/")
STRIPE_CONNECT_REDIRECT_URI = env("STRIPE_CONNECT_REDIRECT_URI", default="")
MANAGED_POSTGRES = env.bool("MANAGED_POSTGRES", default=False)
MANAGED_RESOURCE_LIMITS = {
    "products": 500,
    "assets": 2000,
    "machines": 5,
    "machine_service_open": 100,
    "machine_service_submit": 100,
    "events": 10,
    "bookings": 500,
    "staff": 10,
    "members": 25,
    "storage": 1073741824,
    "print": 200,
    "email": 100,
    "telegram": 100,
    "slack": 100,
    "mattermost": 100,
    "discord": 100,
    "native_push": 500,
    "api_clients": 1,
    "custom_roles": 20,
    # Tenant exports retain a long-lived database snapshot while running. This is an
    # active-job ceiling, independent of the byte quota charged when an archive lands.
    "data_exports": 1,
    "otp_email": 200,
    "otp_sms": 100,
}
# Applies on SELF-HOST TOO, unlike the managed limits above: every auth text is billed
# by the operator's SMS vendor, so this is a cost ceiling rather than a fair-use quota.
# Blank disables the cap entirely.
OTP_SMS_DAILY_CAP = env.int("OTP_SMS_DAILY_CAP", default=200)
ANONYMOUS_REQUEST_OUTSTANDING_LIMIT = env.int(
    "ANONYMOUS_REQUEST_OUTSTANDING_LIMIT",
    default=50,
)
ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH = env.int(
    "ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH",
    default=128,
)
if ANONYMOUS_REQUEST_OUTSTANDING_LIMIT < 1:
    raise ImproperlyConfigured("ANONYMOUS_REQUEST_OUTSTANDING_LIMIT must be positive.")
if ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH < 1:
    raise ImproperlyConfigured(
        "ANONYMOUS_REQUEST_IDEMPOTENCY_KEY_MAX_LENGTH must be positive."
    )
STORAGE_PRESIGN_METHOD = env("STORAGE_PRESIGN_METHOD", default="post")
CRON_SECRET = env("CRON_SECRET", default="")
ADMIN_SITE_NAME = env("ADMIN_SITE_NAME", default="Space Works")
# Whether this deployment has a way into `/control/` that does not use a password.
# There is no such route today -- social sign-in mints JWTs for the React console and
# never a Django session -- so this stays False, and it is what keeps the
# `password_enabled=False` switch from sealing the one page that can turn it back on.
# See `config.admin_access.AdminSuperuserOnlyMiddleware._password_login_blocked`.
# Declared here rather than read with a `getattr` default so that a reader can find it
# and an operator building such a route has somewhere to flip.
PLATFORM_ADMIN_SSO = env.bool("PLATFORM_ADMIN_SSO", default=False)

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "axes",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "storages",
    "apps.accounts",
    "apps.makerspaces",
    "apps.organizations",
    "apps.payments",
    "apps.presence",
    "apps.encryption",
    "apps.apiclients",
    "apps.boxes",
    "apps.inventory",
    "apps.hardware_requests",
    "apps.printing",
    "apps.audit",
    "apps.evidence",
    "apps.warranty",
    "apps.admin_api",
    "apps.data_export",
    "apps.integrations",
    "apps.operations",
    "apps.procurement",
    "apps.notifications",
    "apps.updates",
    "apps.backup",
    "apps.machines",
    "apps.events",
    "apps.bookings",
    "apps.maintenance",
    "apps.roadmap",
    "apps.tenant_migration",
    # Must stay LAST. Django calls ready() in this order, so being last is what
    # guarantees every other app has registered before finalize() freezes the
    # separability registries.
    "apps.separability",
]

# App labels whose runtime surfaces this deployment does not ship: no URLs, no admin
# registration, no sidebar entry, no OpenAPI paths. Rows and migrations are retained,
# and so is the retention registry, so nothing becomes unpurgeable or unencryptable.
# Deployment-scoped rather than per-tenant, because URL routing and the schema are
# process-global. App labels, not module keys -- one app can own several keys.
# A label naming a core module's app is refused at startup (separability.E007).
TOMBSTONED_APPS = tombstoned_app_labels()

MIDDLEWARE = [
    # The recovery gate stays FIRST -- it must refuse a request before any other layer
    # can act on it, and tests/backup/test_recovery_gate.py pins that position.
    "apps.backup.middleware.DeploymentRecoveryGateMiddleware",
    # Second, so it still wraps every view that could log a calendar-feed bearer token.
    "apps.events.middleware.CalendarFeedLogRedactionMiddleware",
    "apps.tenant_migration.middleware.SourceMigrationGateMiddleware",
    "apps.makerspaces.middleware.TenantHostValidationMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "apps.accounts.social_csp.SocialCspMiddleware",
    "csp.middleware.CSPMiddleware",
    "config.admin_access.AdminCspEvalMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "apps.inventory.middleware.FrontendHMACMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.admin_access.AdminSuperuserOnlyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db()}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=0)
DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = env.bool(
    "DISABLE_SERVER_SIDE_CURSORS", default=False
)
SPACEWORKS_HOST_MARKER_PATH = env(
    "SPACEWORKS_HOST_MARKER_PATH",
    default="/run/spaceworks-host/restore-marker.json",
)
BACKUP_PRODUCER_CAPABILITY_MARKER_PATH = env(
    "BACKUP_PRODUCER_CAPABILITY_MARKER_PATH",
    default="/run/spaceworks-host/producer-capability.json",
)
BACKUP_PRODUCER_PRIVILEGED_SCRIPTS_DIR = env(
    "BACKUP_PRODUCER_PRIVILEGED_SCRIPTS_DIR",
    default="/run/spaceworks-privileged-scripts",
)
BACKUP_PRODUCER_ENTRYPOINT_PATH = env(
    "BACKUP_PRODUCER_ENTRYPOINT_PATH",
    default="/app/scripts/spaceworks_entrypoint.py",
)
BACKUP_PRODUCER_MIGRATIONS_DIR = env(
    "BACKUP_PRODUCER_MIGRATIONS_DIR",
    default=str(BASE_DIR / "apps"),
)

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
# PostgreSQL supports 63-character identifiers. The approved Maintenance schema
# intentionally uses a 32-character descriptive index name.
SILENCED_SYSTEM_CHECKS = ["models.E034"]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.auth_backends.SpaceWorksModelBackend",
]

AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
# Axes hooks Django's authenticate(), so it covers BOTH the admin session login and
# the SimpleJWT staff login (apps/accounts LoginView) - intentional brute-force lockout
# on top of that view's DRF rate throttle. The nested list makes the lockout key the
# COMBINATION of ip_address+username (AND), not either alone (OR): repeated failures
# against a known username from other IPs can't lock that account out (no username DoS).
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_ENABLED = env.bool("AXES_ENABLED", default=True)
# django-axes 8 names this setting AXES_IPWARE_PROXY_COUNT. Keep its declared
# topology tied to DRF's and use the shared resolver below so the two protections
# cannot interpret an X-Forwarded-For chain differently.
AXES_IPWARE_PROXY_COUNT = TRUSTED_PROXY_COUNT
AXES_CLIENT_IP_CALLABLE = "config.client_ip.get_throttle_client_ip"

AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="evidence")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="http://localhost:9000")
AWS_S3_PUBLIC_ENDPOINT_URL = env(
    "AWS_S3_PUBLIC_ENDPOINT_URL",
    default=AWS_S3_ENDPOINT_URL,
)
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="us-east-1")
AWS_S3_ADDRESSING_STYLE = "path"
AWS_S3_SIGNATURE_VERSION = "s3v4"
AWS_DEFAULT_ACL = None
AWS_QUERYSTRING_AUTH = True

STORAGES = {
    "default": {"BACKEND": "storages.backends.s3boto3.S3Boto3Storage"},
    # Match prior behavior: plain static storage (whitenoise serves it via middleware).
    # Manifest storage would require collectstatic before runserver, breaking host dev.
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

EVIDENCE_URL_TTL_SECONDS = env.int("EVIDENCE_URL_TTL_SECONDS", default=300)
EVIDENCE_MAX_BYTES = env.int("EVIDENCE_MAX_BYTES", default=10485760)
EVIDENCE_ALLOWED_MIME = ["image/jpeg", "image/png", "image/webp"]
EVIDENCE_OBJECT_RETENTION_DAYS = env.int(
    "EVIDENCE_OBJECT_RETENTION_DAYS", default=365
)
EVIDENCE_OBJECT_EXPIRY_ENABLED = env.bool(
    "EVIDENCE_OBJECT_EXPIRY_ENABLED", default=False
)
EVIDENCE_RETENTION_BATCH_SIZE = env.int("EVIDENCE_RETENTION_BATCH_SIZE", default=100)
WARRANTY_DOC_MAX_BYTES = env.int("WARRANTY_DOC_MAX_BYTES", default=10485760)
WARRANTY_DOC_ALLOWED_MIME = env.list(
    "WARRANTY_DOC_ALLOWED_MIME",
    default=["application/pdf", "image/jpeg", "image/png", "image/webp"],
)
MACHINE_DOC_MAX_BYTES = env.int("MACHINE_DOC_MAX_BYTES", default=10485760)
MACHINE_DOC_ALLOWED_EXT = env.list(
    "MACHINE_DOC_ALLOWED_EXT",
    default=[
        "pdf", "jpg", "jpeg", "png", "webp", "stl", "3mf", "step", "stp",
        "obj", "amf", "ply", "gcode", "gco", "iges", "igs", "dxf",
    ],
)
MACHINE_DOC_ALLOWED_MIME = env.list(
    "MACHINE_DOC_ALLOWED_MIME",
    default=[
        "application/pdf", "image/jpeg", "image/png", "image/webp",
        "application/octet-stream", "model/stl", "application/sla",
        "application/vnd.ms-pki.stl", "model/3mf",
        "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        "application/vnd.ms-3mfdocument", "application/step", "model/step",
        "model/obj", "application/xml", "text/xml", "application/x-amf",
        "model/amf", "application/x-ply", "model/ply", "text/x.gcode",
        "application/x-gcode", "application/iges", "model/iges",
        "image/vnd.dxf", "application/dxf", "application/x-dxf", "text/plain",
    ],
)
PROCUREMENT_RECEIPT_MAX_BYTES = env.int("PROCUREMENT_RECEIPT_MAX_BYTES", default=10485760)
PROCUREMENT_RECEIPT_ALLOWED_MIME = env.list(
    "PROCUREMENT_RECEIPT_ALLOWED_MIME",
    default=["application/pdf", "image/jpeg", "image/png", "image/webp"],
)
PUBLIC_IMAGE_BUCKET = env("PUBLIC_IMAGE_BUCKET", default="public-images")
assert_distinct_storage_buckets(AWS_STORAGE_BUCKET_NAME, PUBLIC_IMAGE_BUCKET)
PUBLIC_IMAGE_BASE_URL = env("PUBLIC_IMAGE_BASE_URL", default="")
PUBLIC_IMAGE_MAX_BYTES = env.int("PUBLIC_IMAGE_MAX_BYTES", default=10485760)
PUBLIC_IMAGE_URL_TTL_SECONDS = env.int("PUBLIC_IMAGE_URL_TTL_SECONDS", default=300)
PUBLIC_IMAGE_ALLOWED_MIME = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
}
PRINT_UPLOAD_MAX_BYTES = env.int("PRINT_UPLOAD_MAX_BYTES", default=104857600)  # 100 MB
PRINT_URL_TTL_SECONDS = env.int("PRINT_URL_TTL_SECONDS", default=300)
PRINT_ALLOWED_MODEL_EXT = env.list(
    "PRINT_ALLOWED_MODEL_EXT",
    default=[
        "stl", "3mf", "step", "stp", "obj", "amf", "ply", "gcode", "gco",
        "iges", "igs", "dxf",
    ],
)
PRINT_ALLOWED_MODEL_MIME = env.list(
    "PRINT_ALLOWED_MODEL_MIME",
    default=[
        "application/octet-stream", "model/stl", "application/sla",
        "application/vnd.ms-pki.stl", "model/3mf",
        "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        "application/vnd.ms-3mfdocument", "application/step", "model/step",
        "model/obj", "application/xml", "text/xml", "application/x-amf",
        "model/amf", "application/x-ply", "model/ply", "text/x.gcode",
        "application/x-gcode", "application/iges", "model/iges",
        "image/vnd.dxf", "application/dxf", "application/x-dxf", "text/plain",
    ],
)
PRINT_ALLOWED_SCREENSHOT_EXT = ["png", "jpg", "jpeg", "webp", "pdf"]
PRINT_ALLOWED_SCREENSHOT_MIME = [
    "image/png",
    "image/jpeg",
    "image/webp",
    "application/pdf",
]

# Read-only token for the GitHub GraphQL API, used only to cache a member's public
# contribution total onto their maker profile. Unset means the feature is dormant: no
# call is made and profiles simply omit the section. Never required.
GITHUB_API_TOKEN = env("GITHUB_API_TOKEN", default="")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_API_URL = env("TELEGRAM_API_URL", default="https://api.telegram.org")
# Secret passed to Telegram's setWebhook(secret_token=...); Telegram echoes it in
# the X-Telegram-Bot-Api-Secret-Token header on every callback. The webhook fails
# closed when this is unset, so an unconfigured webhook can't be driven by spoofed
# callbacks.
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")

EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Makerspace <noreply@makerspace.local>")

# Async email runs through a Celery worker ONLY when a broker is configured (the Compose
# stack + prod set CELERY_BROKER_URL). With no broker - e.g. the documented local flow
# (`docker compose up -d db` + `python manage.py runserver`), or any non-Compose process -
# fall back to EAGER (synchronous) execution so dispatch_email still delivers inline instead
# of enqueuing to an unreachable `redis` host and marking every email failed.
_celery_broker = env("CELERY_BROKER_URL", default="")
CELERY_TASK_ALWAYS_EAGER = env.bool(
    "CELERY_TASK_ALWAYS_EAGER", default=(_celery_broker == "")
)
CELERY_BROKER_URL = _celery_broker or "redis://redis:6379/0"

def cache_config(cache_url):
    """Pick the cache backend, given whatever Redis URL was explicitly configured.

    A per-process cache silently multiplies every DRF rate limit by the worker count and
    loses its counters on each worker recycle. The fallback is therefore Django's
    **DatabaseCache**, never LocMem: the brokerless cloud profile sets an empty
    `CELERY_BROKER_URL` and still runs `gunicorn --workers 3 --max-requests 1000`, so a
    per-process cache would put login, OTP, password-reset and the member image presign
    caps at three times their configured rate and reset them regularly.

    A function rather than an inline expression so the choice is testable against real
    inputs instead of asserted on the live value -- the deployment running the tests is
    not the deployment the rule is about.
    """
    if cache_url:
        return {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": cache_url}
    return {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "spaceworks_cache",
        # MAX_ENTRIES is NOT optional here, and the default would have defeated the point
        # of this whole branch. Django's DatabaseCache defaults to 300 entries and culls a
        # third of them once exceeded. A throttle key is one row per (scope, identity), and
        # this deployment has well over a dozen scoped throttles -- login, public request
        # submit, social nonce and login, password reset, the two phone OTP budgets, public
        # read, member image presign -- so 300 rows is roughly twenty callers before
        # unexpired throttle histories start being evicted. Someone rotating identities
        # could then push a live login or OTP counter out of the cache and reset their own
        # cap, which is precisely the bypass DatabaseCache was chosen to prevent.
        #
        # Culling deletes EXPIRED rows first and only culls by count if still over, so a
        # ceiling this high is effectively never reached: throttle entries expire on their
        # own window, and the rows are tiny.
        "OPTIONS": {"MAX_ENTRIES": 100_000},
    }


_cache_url = env("CACHE_URL", default="") or _celery_broker
CACHES = {"default": cache_config(_cache_url)}

# Under pytest, force LocMem. `DatabaseCache` would make the autouse `cache.clear()` in
# `tests/conftest.py` a DATABASE operation, so every test without the `django_db` mark
# fails with "Database access not allowed" -- 365 of them did. The multi-worker problem
# `DatabaseCache` exists to solve cannot occur in a single-process test run, so LocMem is
# both correct here and the only backend that keeps non-db tests db-free.
#
# Done here rather than with `override_settings(...).enable()` in `pytest_configure`:
# that leaves a global override enabled for the whole session and broke the setup of
# every `transaction=True` test in the suite. Settings are imported by pytest-django
# after pytest itself, so this check is reliable.
if "pytest" in sys.modules:  # pragma: no cover - exercised by running the suite at all
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "spaceworks-tests",
        }
    }

CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="") or None
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# A bounded repeatable-read snapshot is part of the export's correctness contract.
# Operators may tune the bound, but disabling it would pin PostgreSQL vacuum forever.
DATA_EXPORT_DEADLINE_SECONDS = env.int("DATA_EXPORT_DEADLINE_SECONDS", default=900)
DATA_EXPORT_PAGE_SIZE = env.int("DATA_EXPORT_PAGE_SIZE", default=500)
DATA_EXPORT_RETENTION_SECONDS = env.int(
    "DATA_EXPORT_RETENTION_SECONDS", default=7 * 24 * 60 * 60
)
DATA_EXPORT_DOWNLOAD_TTL_SECONDS = env.int(
    "DATA_EXPORT_DOWNLOAD_TTL_SECONDS", default=5 * 60
)
TENANT_MIGRATION_GATE_LEASE_SECONDS = env.int(
    "TENANT_MIGRATION_GATE_LEASE_SECONDS", default=2 * 60 * 60
)
TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS = env.int(
    "TENANT_MIGRATION_PRESIGN_DRAIN_SECONDS",
    default=max(
        EVIDENCE_URL_TTL_SECONDS,
        PUBLIC_IMAGE_URL_TTL_SECONDS,
        PRINT_URL_TTL_SECONDS,
    ),
)
BACKUP_AGE_RECIPIENT = env("BACKUP_AGE_RECIPIENT", default="")
BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY = env(
    "BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY", default=""
)
BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY = env(
    "BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY", default=""
)
TENANT_MIGRATION_AGE_RECIPIENT = env(
    "TENANT_MIGRATION_AGE_RECIPIENT", default=""
)
TENANT_MIGRATION_AGE_IDENTITY_FILE = env(
    "TENANT_MIGRATION_AGE_IDENTITY_FILE", default=""
)
BACKUP_DOWNLOAD_TTL_SECONDS = env.int("BACKUP_DOWNLOAD_TTL_SECONDS", default=5 * 60)
BACKUP_LEASE_SECONDS = env.int("BACKUP_LEASE_SECONDS", default=2 * 60 * 60)
BACKUP_DECISION_SECONDS = env.int("BACKUP_DECISION_SECONDS", default=5 * 60)
BACKUP_RECIPIENT_CHALLENGE_TTL_SECONDS = env.int(
    "BACKUP_RECIPIENT_CHALLENGE_TTL_SECONDS", default=15 * 60
)
BACKUP_PRESIGN_DRAIN_SECONDS = env.int(
    "BACKUP_PRESIGN_DRAIN_SECONDS",
    default=max(EVIDENCE_URL_TTL_SECONDS, PUBLIC_IMAGE_URL_TTL_SECONDS, PRINT_URL_TTL_SECONDS),
)
BACKUP_OPS_DIR = env("BACKUP_OPS_DIR", default="/var/lib/spaceworks/ops")
TENANT_DUMP_STAGING_DIR = env("TENANT_DUMP_STAGING_DIR", default="")
TENANT_DUMP_STAGING_MAX_AGE_SECONDS = env.int(
    "TENANT_DUMP_STAGING_MAX_AGE_SECONDS", default=7 * 24 * 60 * 60
)
# Beat runs return reminders hourly; the internal cron endpoint remains a manual/external fallback.
CELERY_BEAT_SCHEDULE = {
    "flush-api-client-usage": {
        "task": "apps.apiclients.tasks.flush_api_client_usage_task",
        "schedule": crontab(minute="*"),
    },
    "audit-attestation": {
        "task": "apps.audit.tasks.run_audit_attestation_task",
        "schedule": crontab(minute="*/5"),
    },
    # Recovery issuance stays entirely off the anonymous request path. One minute keeps
    # user-visible latency bounded while each invocation still claims a bounded batch.
    "drain-password-reset-envelopes": {
        "task": "apps.accounts.tasks.drain_password_reset_envelopes_task",
        "schedule": crontab(minute="*"),
    },
    "return-reminders": {
        "task": "apps.hardware_requests.tasks.send_return_reminders_task",
        "schedule": crontab(minute=0),
    },
    "evidence-object-expiry": {
        "task": "apps.evidence.tasks.sweep_evidence_retention_task",
        "schedule": crontab(minute=10, hour="*/6"),
    },
    "extend-event-series": {
        "task": "apps.events.tasks.extend_event_series_task",
        "schedule": crontab(minute=10),
    },
    # Spent email/phone verification challenges hold an address or a number and nothing
    # deleted them. Off-peak because it is a pure delete nobody is waiting on.
    "purge-auth-challenges": {
        "task": "apps.accounts.tasks.purge_auth_challenges_task",
        "schedule": crontab(hour=3, minute=30),
    },
    # Maker-profile GitHub counts. Daily and off-peak: the cache interval is 24h, the
    # data is a vanity number, and nothing is waiting on it. A deployment with no
    # GITHUB_API_TOKEN makes no outbound call at all -- the task returns immediately.
    "refresh-github-contributions": {
        "task": "apps.makerspaces.tasks.refresh_github_contributions_task",
        "schedule": crontab(hour=4, minute=15),
    },
    "purge-expired-data-exports": {
        "task": "apps.data_export.tasks.purge_expired_exports_task",
        "schedule": crontab(hour=3, minute=45),
    },
    "finalize-report-rollups": {
        "task": "apps.operations.tasks.finalize_report_rollups_task",
        "schedule": crontab(hour=1, minute=0),
    },
    "scheduled-deployment-backup": {
        "task": "apps.backup.tasks.scheduled_deployment_backup_task",
        "schedule": crontab(hour=2, minute=0),
    },
    "deliver-archive-custody-alarms": {
        "task": "apps.backup.tasks.deliver_archive_custody_alarms_task",
        "schedule": crontab(hour=1, minute=30),
    },
    "deliver-tenant-exit-custody-alarms": {
        "task": "apps.backup.tasks.deliver_tenant_exit_custody_alarms_task",
        "schedule": crontab(minute=45),
    },
    "reconcile-backup-artifacts": {
        "task": "apps.backup.tasks.reconcile_backup_artifacts_task",
        "schedule": crontab(minute="*/5"),
    },
    "purge-expired-backup-archives": {
        "task": "apps.backup.tasks.purge_expired_backup_archives_task",
        "schedule": crontab(hour=3, minute=55),
    },
    "cleanup-expired-restore-rollbacks": {
        "task": "apps.backup.tasks.cleanup_expired_restore_rollbacks_task",
        "schedule": crontab(hour=4, minute=5),
    },
    "cleanup-expired-tenant-import-jobs": {
        "task": "apps.tenant_migration.tasks.cleanup_expired_import_jobs_task",
        "schedule": crontab(minute=20),
    },
    "cleanup-abandoned-tenant-import-objects": {
        "task": "apps.tenant_migration.tasks.cleanup_abandoned_import_objects_task",
        "schedule": crontab(minute=35),
    },
    "cleanup-refused-tenant-dump-artifacts": {
        "task": "apps.tenant_migration.tasks.cleanup_refused_tenant_dump_artifacts_task",
        "schedule": crontab(minute=40),
    },
    "resume-expired-tenant-import-finalizations": {
        "task": "apps.tenant_migration.tasks.resume_expired_finalizing_import_jobs_task",
        "schedule": crontab(minute="*/5"),
    },
}
if "tenant_migration" in TOMBSTONED_APPS:
    CELERY_BEAT_SCHEDULE = {
        name: entry
        for name, entry in CELERY_BEAT_SCHEDULE.items()
        if ".tenant_migration." not in entry["task"]
    }
if "events" in TOMBSTONED_APPS:
    CELERY_BEAT_SCHEDULE = {
        name: entry
        for name, entry in CELERY_BEAT_SCHEDULE.items()
        if ".events." not in entry["task"]
    }

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5000", "http://localhost:5173"],
)
CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-client-id",
    "x-nonce",
    "x-signature",
    "x-timestamp",
    "x-refresh-csrf",
    "x-station-csrf",
    "x-publishable-key",
)
CORS_ALLOW_CREDENTIALS = True

HMAC_CLIENT_ID = env("HMAC_CLIENT_ID", default="")
HMAC_SECRET = env("HMAC_SECRET", default="")
HMAC_MAX_CLOCK_SKEW_SECONDS = env.int("HMAC_MAX_CLOCK_SKEW_SECONDS", default=300)
APICLIENT_REQUIRE_NONCE = env.bool("APICLIENT_REQUIRE_NONCE", default=False)
HMAC_PROTECTED_PATH_PREFIXES = env.list(
    "HMAC_PROTECTED_PATH_PREFIXES",
    default=["/api/public/", "/api/v1/public/"],
)
# Fernet key for encrypting ApiClient secrets at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# default="" (review fix #5) so settings import never fails when encryption isn't used;
# _fernet() raises ImproperlyConfigured only when a key is actually needed. Tests/CI get a
# real key from .env / docker-compose (added below).
API_CLIENT_ENC_KEY = env("API_CLIENT_ENC_KEY", default="")
# Dedicated domain-separation secret for event-station PIN verification. The raw PIN
# is encrypted with API_CLIENT_ENC_KEY only because staff reveal is an explicit product
# requirement; the slow hash plus this independent pepper remains the verifier.
EVENT_STATION_PIN_PEPPER = env("EVENT_STATION_PIN_PEPPER", default="")
EVENT_CHECKIN_WINDOW_BEFORE_HOURS = env.int(
    "EVENT_CHECKIN_WINDOW_BEFORE_HOURS", default=24
)
EVENT_CHECKIN_WINDOW_AFTER_HOURS = env.int(
    "EVENT_CHECKIN_WINDOW_AFTER_HOURS", default=2
)
EVENT_CHECKIN_SYNC_GRACE_HOURS = env.int(
    "EVENT_CHECKIN_SYNC_GRACE_HOURS", default=24
)
EVENT_CHECKIN_ROSTER_LIFETIME_HOURS = env.int(
    "EVENT_CHECKIN_ROSTER_LIFETIME_HOURS", default=24
)
EVENT_CHECKIN_CLOCK_SKEW_SECONDS = env.int(
    "EVENT_CHECKIN_CLOCK_SKEW_SECONDS", default=300
)
EVENT_CHECKIN_ROSTER_MAX = env.int("EVENT_CHECKIN_ROSTER_MAX", default=1000)
# Wraps the per-scope audit row-MAC keys. Independent of PII_MASTER_KEY on purpose: the
# audit domain gets its own key so a PII key rotation cannot invalidate integrity
# evidence. Empty means row-MAC attestation is OFF and new audit rows are stored
# unattested (see apps.audit.checks, which warns at startup).
AUDIT_MAC_MASTER_KEY = env("AUDIT_MAC_MASTER_KEY", default="")

# Batch attestation (AUD-2). Anchoring is what makes tampering detectable to someone who
# controls the box, so the sink config lives here rather than in the database.
AUDIT_ATTESTATION_DEPLOYMENT_ID = env("AUDIT_ATTESTATION_DEPLOYMENT_ID", default="")
AUDIT_ATTESTATION_ANCHOR_BACKEND = env("AUDIT_ATTESTATION_ANCHOR_BACKEND", default="")
AUDIT_ATTESTATION_S3_BUCKET = env("AUDIT_ATTESTATION_S3_BUCKET", default="")
AUDIT_ATTESTATION_S3_PREFIX = env(
    "AUDIT_ATTESTATION_S3_PREFIX", default="spaceworks-audit/v1"
)
AUDIT_ATTESTATION_RETENTION_DAYS = env.int(
    "AUDIT_ATTESTATION_RETENTION_DAYS", default=2555
)
AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE = env(
    "AUDIT_ATTESTATION_S3_OBJECT_LOCK_MODE", default="COMPLIANCE"
)
AUDIT_ATTESTATION_S3_ENDPOINT_URL = env(
    "AUDIT_ATTESTATION_S3_ENDPOINT_URL", default=AWS_S3_ENDPOINT_URL
)
AUDIT_ATTESTATION_S3_ACCESS_KEY_ID = env(
    "AUDIT_ATTESTATION_S3_ACCESS_KEY_ID", default=AWS_ACCESS_KEY_ID
)
AUDIT_ATTESTATION_S3_SECRET_ACCESS_KEY = env(
    "AUDIT_ATTESTATION_S3_SECRET_ACCESS_KEY", default=AWS_SECRET_ACCESS_KEY
)
AUDIT_ATTESTATION_S3_REGION_NAME = env(
    "AUDIT_ATTESTATION_S3_REGION_NAME", default=AWS_S3_REGION_NAME
)
AUDIT_ATTESTATION_HTTP_URL = env("AUDIT_ATTESTATION_HTTP_URL", default="")
AUDIT_ATTESTATION_HTTP_BEARER_TOKEN = env(
    "AUDIT_ATTESTATION_HTTP_BEARER_TOKEN", default=""
)
AUDIT_ATTESTATION_HTTP_TIMEOUT = env.float("AUDIT_ATTESTATION_HTTP_TIMEOUT", default=10)
# Scoped requester/contact PII encryption is intentionally dormant by default.  These
# values are read lazily by the encryption broker so a disabled installation needs no
# key material or optional KMS dependency.
PII_ENCRYPTION_ENABLED = env.bool("PII_ENCRYPTION_ENABLED", default=False)
PII_ENCRYPTION_DUAL_READ = env.bool("PII_ENCRYPTION_DUAL_READ", default=True)
PII_KEY_BROKER = env("PII_KEY_BROKER", default="local")
PII_MASTER_KEY = env("PII_MASTER_KEY", default="")
PII_MASTER_KEY_PREVIOUS = env("PII_MASTER_KEY_PREVIOUS", default="")
PII_SEARCH_HASH_KEY = env("PII_SEARCH_HASH_KEY", default="")
PII_DEK_CACHE_TTL_SECONDS = env.int("PII_DEK_CACHE_TTL_SECONDS", default=300)
PII_AWS_KMS_KEY_ID = env("PII_AWS_KMS_KEY_ID", default="")
PII_AWS_KMS_REGION = env("PII_AWS_KMS_REGION", default="")
PII_AWS_KMS_ENDPOINT_URL = env("PII_AWS_KMS_ENDPOINT_URL", default="")
# When True, requests to HMAC_PROTECTED_PATH_PREFIXES must carry a valid signed client.
API_CLIENT_AUTH_REQUIRED = env.bool("API_CLIENT_AUTH_REQUIRED", default=False)

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 24,
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.SpaceWorksJWTAuthentication",
    ),
    # DENY BY DEFAULT (review fix #4): every view requires auth unless it explicitly
    # opts into AllowAny. Public views are marked AllowAny in Step 3b.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "EXCEPTION_HANDLER": "apps.hardware_requests.exceptions.workflow_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "login": env("THROTTLE_LOGIN", default="10/min"),
        "device_attestation_challenge": env("THROTTLE_DEVICE_ATTESTATION_CHALLENGE", default="5/min"),
        "device_login": env("THROTTLE_DEVICE_LOGIN", default="5/min"),
        "device_login_user": env("THROTTLE_DEVICE_LOGIN_USER", default="10/hour"),
        "device_refresh": env("THROTTLE_DEVICE_REFRESH", default="30/min"),
        "push_device_registration": env("THROTTLE_PUSH_DEVICE_REGISTRATION", default="10/min"),
        "social_nonce": env("THROTTLE_SOCIAL_NONCE", default="10/min"),
        "social_login": env("THROTTLE_SOCIAL_LOGIN", default="10/min"),
        # Issuance and redemption deliberately have independent budgets. A member who
        # mistypes a physically handed code must not consume the staff issue budget (or
        # vice versa), repeating the phone-OTP shared-bucket failure.
        "member_claim_issue": env("THROTTLE_MEMBER_CLAIM_ISSUE", default="10/hour"),
        "member_claim_redeem": env("THROTTLE_MEMBER_CLAIM_REDEEM", default="10/min"),
        # Tighter than the email OTP rates: every one of these costs the operator money
        # and lands on a stranger's handset if the number is wrong.
        "phone_otp_request": env("THROTTLE_PHONE_OTP_REQUEST", default="5/min"),
        "phone_otp_number": env("THROTTLE_PHONE_OTP_NUMBER", default="5/hour"),
        "phone_login_confirm": env("THROTTLE_PHONE_LOGIN_CONFIRM", default="10/min"),
        "phone_confirm_number": env("THROTTLE_PHONE_CONFIRM_NUMBER", default="15/hour"),
        "password_reset_request": env(
            "THROTTLE_PASSWORD_RESET_REQUEST",
            default="5/min",
        ),
        "password_reset_email": env(
            "THROTTLE_PASSWORD_RESET_EMAIL",
            default="5/hour",
        ),
        "password_reset_confirm": env(
            "THROTTLE_PASSWORD_RESET_CONFIRM",
            default="10/min",
        ),
        "password_reset_confirm_email": env(
            "THROTTLE_PASSWORD_RESET_CONFIRM_EMAIL",
            default="15/hour",
        ),
        "member_sign_up": env("THROTTLE_MEMBER_SIGN_UP", default="5/min"),
        "email_verification_resend": env(
            "THROTTLE_EMAIL_VERIFICATION_RESEND", default="5/min"
        ),
        "email_verification_confirm": env(
            "THROTTLE_EMAIL_VERIFICATION_CONFIRM", default="10/min"
        ),
        "member_verification_email": env(
            "THROTTLE_MEMBER_VERIFICATION_EMAIL", default="5/hour"
        ),
        "telegram_webhook": env("THROTTLE_TELEGRAM_WEBHOOK", default="60/min"),
        "public_request_submit": env(
            "THROTTLE_PUBLIC_REQUEST_SUBMIT",
            default="10/min",
        ),
        "anonymous_request_ip_burst": env(
            "THROTTLE_ANONYMOUS_REQUEST_IP_BURST",
            default="2/min",
        ),
        "anonymous_request_ip_hour": env(
            "THROTTLE_ANONYMOUS_REQUEST_IP_HOUR",
            default="10/hour",
        ),
        "anonymous_request_email": env(
            "THROTTLE_ANONYMOUS_REQUEST_EMAIL",
            default="3/day",
        ),
        "print_request_submit": env("THROTTLE_PRINT_REQUEST_SUBMIT", default="10/min"),
        "public_tool_checkout": env("THROTTLE_PUBLIC_TOOL_CHECKOUT", default="10/min"),
        "public_tool_return": env("THROTTLE_PUBLIC_TOOL_RETURN", default="10/min"),
        "request_submit": env("THROTTLE_REQUEST_SUBMIT", default="10/min"),
        "request_status": env("THROTTLE_REQUEST_STATUS", default="60/min"),
        "public_read": env("THROTTLE_PUBLIC_READ", default="120/min"),
        "event_register": env("THROTTLE_EVENT_REGISTER", default="10/hour"),
        "event_registration_retry": env(
            "THROTTLE_EVENT_REGISTRATION_RETRY", default="30/hour"
        ),
        "event_checkin_resolve": env(
            "THROTTLE_EVENT_CHECKIN_RESOLVE", default="60/min"
        ),
        "event_offline_roster": env(
            "THROTTLE_EVENT_OFFLINE_ROSTER", default="10/hour"
        ),
        "event_offline_sync": env(
            "THROTTLE_EVENT_OFFLINE_SYNC", default="60/hour"
        ),
        "event_station_pin_token": env(
            "THROTTLE_EVENT_STATION_PIN_TOKEN", default="10/hour"
        ),
        "event_station_pin_ip": env(
            "THROTTLE_EVENT_STATION_PIN_IP", default="30/hour"
        ),
        "event_station_session": env(
            "THROTTLE_EVENT_STATION_SESSION", default="120/hour"
        ),
        "event_station_reveal": env(
            "THROTTLE_EVENT_STATION_REVEAL", default="5/hour"
        ),
        "event_calendar_feed_token": env(
            "THROTTLE_EVENT_CALENDAR_FEED_TOKEN", default="120/hour"
        ),
        "event_calendar_feed_ip": env(
            "THROTTLE_EVENT_CALENDAR_FEED_IP", default="300/hour"
        ),
        "public_stats": env("THROTTLE_PUBLIC_STATS", default="30/min"),
        "client_public": env("THROTTLE_CLIENT_PUBLIC", default="30/min"),
        "client_standard": env("THROTTLE_CLIENT_STANDARD", default="120/min"),
        "client_trusted": env("THROTTLE_CLIENT_TRUSTED", default="600/min"),
        'booking_submit': env('THROTTLE_BOOKING_SUBMIT', default='10/hour'),
        "membership_request": env("THROTTLE_MEMBERSHIP_REQUEST", default="10/hour"),
        "presence_start": env("THROTTLE_PRESENCE_START", default="10/hour"),
        # A presigned upload can be requested and never attached, stranding an object
        # that no row names and no quota counts. Generous for the real workflow -- an
        # avatar plus a handful of project images -- and a hard ceiling on how much one
        # member can strand. See `makerspaces.throttles.MemberImagePresignThrottle`.
        "member_image_presign": env("THROTTLE_MEMBER_IMAGE_PRESIGN", default="20/hour"),
        "data_export_create": env("THROTTLE_DATA_EXPORT_CREATE", default="3/hour"),
        "archive_recipient_verify": env(
            "THROTTLE_ARCHIVE_RECIPIENT_VERIFY", default="10/min"
        ),
        "tenant_migration_read": env(
            "THROTTLE_TENANT_MIGRATION_READ", default="120/min"
        ),
        "tenant_migration_write": env(
            "THROTTLE_TENANT_MIGRATION_WRITE", default="30/hour"
        ),
    },
    # Proxy-aware client IP for throttling. Production must declare its topology at
    # settings import above; direct DEBUG development defaults to zero trusted proxies.
    # A positive count selects the Nth-from-last XFF entry appended by trusted proxies.
    "NUM_PROXIES": TRUSTED_PROXY_COUNT,
    "URL_FORMAT_OVERRIDE": None,
}

# TLS-dependent hardening. Gated behind ENABLE_HTTPS (env), NOT DEBUG: the default
# Docker/prod compose serves plain HTTP and must not trust client-supplied forwarded
# proto headers. TLS overlays set TRUST_X_FORWARDED_PROTO=true only when a trusted
# reverse proxy is the sole path to the backend.
ENABLE_HTTPS = env.bool("ENABLE_HTTPS", default=False)
TRUST_X_FORWARDED_PROTO = env.bool("TRUST_X_FORWARDED_PROTO", default=False)
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if TRUST_X_FORWARDED_PROTO else None
)
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=ENABLE_HTTPS)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=ENABLE_HTTPS)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=ENABLE_HTTPS)
# Needed for admin/login POST when reached over HTTPS via a custom domain behind a
# proxy. Same-origin HTTP needs nothing here; set to the public https origin(s) when
# ENABLE_HTTPS is on, e.g. CSRF_TRUSTED_ORIGINS=https://makerspace.example.org
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
SECURE_HSTS_SECONDS = env.int(
    "SECURE_HSTS_SECONDS", default=31536000 if ENABLE_HTTPS else 0
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# Always-on, transport-independent headers.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Permissive enough for the current admin and API docs; tighten per deployment later.
# drf-spectacular's Swagger UI / Redoc load their JS+CSS from the jsDelivr CDN, so the
# CDN is allowed for script/style/img/font; drop it (or adopt drf-spectacular-sidecar to
# serve the assets from 'self') once the docs UI is locally hosted.
_SWAGGER_CDN = "https://cdn.jsdelivr.net"
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        # 'wasm-unsafe-eval' lets the in-browser QR scanner instantiate the bundled
        # zxing-wasm reader (the camera fallback on browsers without a native
        # BarcodeDetector). It permits ONLY WebAssembly compilation, NOT arbitrary
        # JS eval, so it is far narrower than 'unsafe-eval'.
        "script-src": ["'self'", "'unsafe-inline'", "'wasm-unsafe-eval'", _SWAGGER_CDN],
        "style-src": ["'self'", "'unsafe-inline'", _SWAGGER_CDN],
        "img-src": ["'self'", "data:", _SWAGGER_CDN],
        "font-src": ["'self'", "data:", _SWAGGER_CDN],
        "worker-src": ["'self'", "blob:"],
    }
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_TOKEN_CLASSES": (
        "apps.accounts.tokens.SpaceWorksAccessToken",
        "apps.accounts.claim_tokens.ClaimAccessToken",
    ),
}

# Cross-site refresh cookie (frontends live on separate origins).
AUTH_REFRESH_COOKIE = "refresh_token"
# CSRF defense for the cookie-bearing endpoints (refresh/logout): the view requires
# this custom header to be PRESENT - a non-simple header forces a CORS preflight that
# an attacker's origin cannot pass - AND validates the Origin header against the
# allowlist (review fixes #1, #8). The header VALUE is not a secret; presence + Origin
# is the defense. This works cross-origin where a readable double-submit cookie cannot.
AUTH_REFRESH_CSRF_HEADER = "X-Refresh-CSRF"
AUTH_COOKIE_PATH = "/api/v1/auth/"
# SameSite=None REQUIRES Secure or browsers silently drop the cookie (review fix #2).
# Prod (separate origins over HTTPS): SAMESITE=None, SECURE=True.
# Local dev: serve the frontend through a same-origin Vite proxy to the API and set
# AUTH_COOKIE_SAMESITE=Lax + AUTH_COOKIE_SECURE=False via .env (see Step 3c note).
AUTH_COOKIE_SAMESITE = env("AUTH_COOKIE_SAMESITE", default="None")
AUTH_COOKIE_SECURE = env.bool("AUTH_COOKIE_SECURE", default=True)

# Native device routes are dormant until an exact app allowlist and both the selected
# provider verifier URL and bearer credential are configured. Verifiers must perform
# real Apple App Attest / Google Play Integrity validation and return bound claims.
DEVICE_ATTESTATION_APPS = env.json("DEVICE_ATTESTATION_APPS", default={})
DEVICE_APPLE_ATTESTATION_VERIFY_URL = env("DEVICE_APPLE_ATTESTATION_VERIFY_URL", default="")
DEVICE_APPLE_ATTESTATION_VERIFY_TOKEN = env("DEVICE_APPLE_ATTESTATION_VERIFY_TOKEN", default="")
DEVICE_ANDROID_ATTESTATION_VERIFY_URL = env("DEVICE_ANDROID_ATTESTATION_VERIFY_URL", default="")
DEVICE_ANDROID_ATTESTATION_VERIFY_TOKEN = env("DEVICE_ANDROID_ATTESTATION_VERIFY_TOKEN", default="")
DEVICE_ATTESTATION_CHALLENGE_TTL_SECONDS = env.int("DEVICE_ATTESTATION_CHALLENGE_TTL_SECONDS", default=180)
DEVICE_ATTESTATION_PROVIDER_TIMEOUT_SECONDS = env.int("DEVICE_ATTESTATION_PROVIDER_TIMEOUT_SECONDS", default=10)
PUSH_TOKEN_HMAC_KEY = env("PUSH_TOKEN_HMAC_KEY", default="")
SOCIAL_AUTH_NONCE_TTL_SECONDS = env.int("SOCIAL_AUTH_NONCE_TTL_SECONDS", default=300)
SOCIAL_AUTH_CLOCK_SKEW_SECONDS = env.int("SOCIAL_AUTH_CLOCK_SKEW_SECONDS", default=60)
SOCIAL_AUTH_JWKS_TIMEOUT_SECONDS = env.int("SOCIAL_AUTH_JWKS_TIMEOUT_SECONDS", default=5)
SOCIAL_AUTH_JWKS_CACHE_SECONDS = env.int("SOCIAL_AUTH_JWKS_CACHE_SECONDS", default=3600)
SOCIAL_AUTH_JWKS_MAX_BYTES = env.int("SOCIAL_AUTH_JWKS_MAX_BYTES", default=1048576)
OIDC_ATTEMPT_TTL_SECONDS = env.int("OIDC_ATTEMPT_TTL_SECONDS", default=300)
OIDC_HTTP_TIMEOUT_SECONDS = env.int("OIDC_HTTP_TIMEOUT_SECONDS", default=5)
OIDC_HTTP_MAX_BYTES = env.int("OIDC_HTTP_MAX_BYTES", default=65536)
OIDC_DISCOVERY_CACHE_SECONDS = env.int("OIDC_DISCOVERY_CACHE_SECONDS", default=300)
MEMBER_CLAIM_CODE_TTL_SECONDS = env.int(
    "MEMBER_CLAIM_CODE_TTL_SECONDS", default=15 * 60
)
MEMBER_CLAIM_SESSION_TTL_SECONDS = env.int(
    "MEMBER_CLAIM_SESSION_TTL_SECONDS", default=12 * 60 * 60
)
SOCIAL_GOOGLE_JWKS_URL = env("SOCIAL_GOOGLE_JWKS_URL", default="https://www.googleapis.com/oauth2/v3/certs")
SOCIAL_APPLE_JWKS_URL = env("SOCIAL_APPLE_JWKS_URL", default="https://appleid.apple.com/auth/keys")

SPECTACULAR_SETTINGS = {
    "TITLE": "Space Works API",
    "DESCRIPTION": (
        "Multi-tenant makerspace hardware loan system.\n\n"
        "Public flow: browse inventory, search with `q`, page with `page`, "
        "sign in as a member, submit a borrow request, then track it by public token.\n\n"
        "Admin flow: authenticate with JWT, manage makerspaces, inventory, "
        "staff, QR labels, bulk imports, request review, issue, and return.\n\n"
        "Authentication: staff/admin endpoints use `Authorization: Bearer <access>`. "
        "Public browser endpoints can use `X-Publishable-Key` when public key "
        "hardening is enabled. Server API clients send `X-Client-Id`, `X-Timestamp`, "
        "`X-Nonce`, and `X-Signature`. Generate a unique, unpredictable `X-Nonce` "
        "for every request and sign the byte sequence "
        "`METHOD\\nFULL_PATH\\nTIMESTAMP\\nNONCE\\nBODY` with HMAC-SHA256. "
        "The nonce uses 1-128 characters from `A-Z`, `a-z`, `0-9`, `.`, `_`, `~`, "
        "and `-`. A deployment may temporarily accept the legacy nonce-less signed "
        "format while `APICLIENT_REQUIRE_NONCE` is disabled."
    ),
    # Kept in step with the root `VERSION` file by
    # `tests/test_version_consistency.py`. It cannot simply READ that file: the backend
    # image is built with `context: ./backend`, so the repo root is outside the build
    # context and the file does not exist inside the container.
    "VERSION": "0.8.1",
    "ENUM_NAME_OVERRIDES": {
        "QrPrintBatchStatusEnum": [
            ("draft", "Draft"),
            ("printed", "Printed"),
            ("archived", "Archived"),
        ],
        "InventoryAssetStatusEnum": [
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("issued", "Issued"),
            ("damaged", "Damaged"),
            ("lost", "Lost"),
            ("retired", "Retired"),
            ("maintenance", "Maintenance"),
        ],
    },
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVERS": [
        {"url": "http://localhost:8001", "description": "Local Docker backend"},
        {"url": "http://localhost:8000", "description": "Local Django runserver"},
    ],
    "TAGS": [
        {"name": "Auth", "description": "Staff login, refresh, logout, and profile."},
        {"name": "Public inventory", "description": "Public makerspace catalog browsing."},
        {"name": "Public requests", "description": "Public borrow request and status flows."},
        {"name": "Admin makerspaces", "description": "Admin makerspace CRUD."},
        {"name": "Admin inventory", "description": "Admin inventory CRUD and search lists."},
        {"name": "Admin requests", "description": "Review, handover, issue, and return workflows."},
        {"name": "Bulk import", "description": "Inventory import preview and apply workflow."},
        {"name": "Admin users", "description": "Staff, guest-admin, and access restriction."},
        {"name": "QR assets", "description": "QR-coded boxes, tools, scans, print, revoke."},
        {"name": "Telegram", "description": "Telegram webhook and alert integration."},
        {"name": "Printing", "description": "3D printing request and management APIs."},
        {"name": "Payments", "description": "Stripe payment configuration and verified webhooks."},
        {"name": "Containers", "description": "Container hierarchy, movement, contents, and scan history."},
        {"name": "Stock transfers", "description": "Administrative stock movement between containers and makerspaces."},
        {"name": "Stocktake", "description": "Stocktake sessions, line counts, approvals, and adjustments."},
        {"name": "Analytics", "description": "Operational inventory analytics and report summaries."},
        {"name": "Reports", "description": "CSV and XLSX operational report exports."},
        {"name": "QR print batches", "description": "QR label batch creation, item management, and print HTML."},
        {"name": "Asset units", "description": "Individual asset unit generation and QR assignment."},
        {"name": "Health", "description": "Health and readiness probes."},
        {"name": "Notifications", "description": "Persistent staff inbox notifications."},
    ],
}
