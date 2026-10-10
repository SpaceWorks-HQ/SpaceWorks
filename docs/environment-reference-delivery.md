# Delivery, sign-in and rate-limit environment settings

Part of the [complete environment reference](environment-reference.md).

## Email, Telegram and outbound integrations

Platform SMTP, SMS, push and Stripe Connect credentials normally live encrypted in the database (`/control/` and the Platform settings panel); these variables are the deployment-level fallbacks.

| Variable | Default | Notes |
|---|---|---|
| `DEFAULT_FROM_EMAIL` | `'Makerspace <noreply@makerspace.local>'` |  |
| `EMAIL_BACKEND` | `'django.core.mail.backends.console.EmailBackend'` | Must be the SMTP backend for `email_enabled()` to report on. |
| `EMAIL_HOST` | `''` |  |
| `EMAIL_HOST_PASSWORD` | `''` |  |
| `EMAIL_HOST_USER` | `''` |  |
| `EMAIL_PORT` | `587` |  |
| `EMAIL_USE_TLS` | `True` |  |
| `GITHUB_API_TOKEN` | `''` | Optional; raises the GitHub rate limit for maker-profile contribution refresh. |
| `OTP_SMS_DAILY_CAP` | `200` | Platform-wide daily cap on SMS sign-in codes. |
| `PUSH_TOKEN_HMAC_KEY` | `''` | Keys the device-token digest; push registration answers 503 while unset. |
| `STRIPE_CONNECT_REDIRECT_URI` | `''` |  |
| `TELEGRAM_API_URL` | `'https://api.telegram.org'` |  |
| `TELEGRAM_BOT_TOKEN` | `''` |  |
| `TELEGRAM_WEBHOOK_SECRET` | `''` | The webhook answers 403 while unset; callbacks are acknowledged and ignored. |

## Sign-in: social, OIDC, native devices, member claims

| Variable | Default | Notes |
|---|---|---|
| `DEVICE_ANDROID_ATTESTATION_VERIFY_TOKEN` | `''` |  |
| `DEVICE_ANDROID_ATTESTATION_VERIFY_URL` | `''` |  |
| `DEVICE_APPLE_ATTESTATION_VERIFY_TOKEN` | `''` |  |
| `DEVICE_APPLE_ATTESTATION_VERIFY_URL` | `''` |  |
| `DEVICE_ATTESTATION_APPS` | `{}` |  |
| `DEVICE_ATTESTATION_CHALLENGE_TTL_SECONDS` | `180` |  |
| `DEVICE_ATTESTATION_PROVIDER_TIMEOUT_SECONDS` | `10` |  |
| `MEMBER_CLAIM_CODE_TTL_SECONDS` | `15 * 60` |  |
| `MEMBER_CLAIM_SESSION_TTL_SECONDS` | `12 * 60 * 60` |  |
| `OIDC_ATTEMPT_TTL_SECONDS` | `300` |  |
| `OIDC_DISCOVERY_CACHE_SECONDS` | `300` |  |
| `OIDC_HTTP_MAX_BYTES` | `65536` |  |
| `OIDC_HTTP_TIMEOUT_SECONDS` | `5` |  |
| `SOCIAL_APPLE_JWKS_URL` | `'https://appleid.apple.com/auth/keys'` |  |
| `SOCIAL_AUTH_CLOCK_SKEW_SECONDS` | `60` |  |
| `SOCIAL_AUTH_JWKS_CACHE_SECONDS` | `3600` |  |
| `SOCIAL_AUTH_JWKS_MAX_BYTES` | `1048576` |  |
| `SOCIAL_AUTH_JWKS_TIMEOUT_SECONDS` | `5` |  |
| `SOCIAL_AUTH_NONCE_TTL_SECONDS` | `300` |  |
| `SOCIAL_GOOGLE_JWKS_URL` | `'https://www.googleapis.com/oauth2/v3/certs'` |  |

## Rate limits

Every `THROTTLE_*` value is a DRF rate string (`<n>/<second|minute|hour|day>`). Defaults are correct in production; raise one only with a reason.

| Variable | Default | Notes |
|---|---|---|
| `THROTTLE_ANONYMOUS_REQUEST_EMAIL` | `'3/day'` |  |
| `THROTTLE_ANONYMOUS_REQUEST_IP_BURST` | `'2/min'` |  |
| `THROTTLE_ANONYMOUS_REQUEST_IP_HOUR` | `'10/hour'` |  |
| `THROTTLE_ARCHIVE_RECIPIENT_VERIFY` | `'10/min'` |  |
| `THROTTLE_AUDIT_VERIFICATION` | `'6/hour'` | On-demand audit chain verification runs. |
| `THROTTLE_BOOKING_SUBMIT` | `'10/hour'` |  |
| `THROTTLE_DATA_EXPORT_CREATE` | `'3/hour'` |  |
| `THROTTLE_DEVICE_ATTESTATION_CHALLENGE` | `'5/min'` |  |
| `THROTTLE_DEVICE_LOGIN` | `'5/min'` |  |
| `THROTTLE_DEVICE_LOGIN_USER` | `'10/hour'` |  |
| `THROTTLE_DEVICE_REFRESH` | `'30/min'` |  |
| `THROTTLE_EMAIL_VERIFICATION_CONFIRM` | `'10/min'` |  |
| `THROTTLE_EMAIL_VERIFICATION_RESEND` | `'5/min'` |  |
| `THROTTLE_EVENT_CALENDAR_FEED_IP` | `'300/hour'` |  |
| `THROTTLE_EVENT_CALENDAR_FEED_TOKEN` | `'120/hour'` |  |
| `THROTTLE_EVENT_CHECKIN_RESOLVE` | `'60/min'` |  |
| `THROTTLE_EVENT_OFFLINE_ROSTER` | `'10/hour'` |  |
| `THROTTLE_EVENT_OFFLINE_SYNC` | `'60/hour'` |  |
| `THROTTLE_EVENT_REGISTER` | `'10/hour'` |  |
| `THROTTLE_EVENT_REGISTRATION_RETRY` | `'30/hour'` |  |
| `THROTTLE_EVENT_STATION_PIN_IP` | `'30/hour'` |  |
| `THROTTLE_EVENT_STATION_PIN_TOKEN` | `'10/hour'` |  |
| `THROTTLE_EVENT_STATION_REVEAL` | `'5/hour'` |  |
| `THROTTLE_EVENT_STATION_SESSION` | `'120/hour'` |  |
| `THROTTLE_KIOSK_OPERATOR_LEASE` | `'30/hour'` |  |
| `THROTTLE_KIOSK_REPLAY_EXECUTE` | `'240/hour'` |  |
| `THROTTLE_KIOSK_REPLAY_PREPARE` | `'60/hour'` |  |
| `THROTTLE_KIOSK_STATION_PIN_IP` | `'30/hour'` |  |
| `THROTTLE_KIOSK_STATION_PIN_TOKEN` | `'10/hour'` |  |
| `THROTTLE_KIOSK_STATION_SESSION` | `'120/hour'` |  |
| `THROTTLE_LOGIN` | `'10/min'` |  |
| `THROTTLE_MEMBERSHIP_REQUEST` | `'10/hour'` |  |
| `THROTTLE_MEMBER_CLAIM_ISSUE` | `'10/hour'` |  |
| `THROTTLE_MEMBER_CLAIM_REDEEM` | `'10/min'` |  |
| `THROTTLE_MEMBER_IMAGE_PRESIGN` | `'20/hour'` |  |
| `THROTTLE_MEMBER_SIGN_UP` | `'5/min'` |  |
| `THROTTLE_MEMBER_VERIFICATION_EMAIL` | `'5/hour'` |  |
| `THROTTLE_PASSWORD_RESET_CONFIRM` | `'10/min'` |  |
| `THROTTLE_PASSWORD_RESET_CONFIRM_EMAIL` | `'15/hour'` |  |
| `THROTTLE_PASSWORD_RESET_EMAIL` | `'5/hour'` |  |
| `THROTTLE_PASSWORD_RESET_REQUEST` | `'5/min'` |  |
| `THROTTLE_PHONE_CONFIRM_NUMBER` | `'15/hour'` |  |
| `THROTTLE_PHONE_LOGIN_CONFIRM` | `'10/min'` |  |
| `THROTTLE_PHONE_OTP_NUMBER` | `'5/hour'` |  |
| `THROTTLE_PHONE_OTP_REQUEST` | `'5/min'` |  |
| `THROTTLE_PRESENCE_START` | `'10/hour'` |  |
| `THROTTLE_PRINT_REQUEST_SUBMIT` | `'10/min'` |  |
| `THROTTLE_PUBLIC_INVITATION_REQUEST` | `'10/hour'` |  |
| `THROTTLE_PUBLIC_READ` | `'120/min'` |  |
| `THROTTLE_PUBLIC_REQUEST_SUBMIT` | `'10/min'` |  |
| `THROTTLE_PUBLIC_STATS` | `'30/min'` |  |
| `THROTTLE_PUBLIC_TOOL_CHECKOUT` | `'10/min'` |  |
| `THROTTLE_PUBLIC_TOOL_RETURN` | `'10/min'` |  |
| `THROTTLE_PUSH_DEVICE_REGISTRATION` | `'10/min'` |  |
| `THROTTLE_REQUEST_STATUS` | `'60/min'` |  |
| `THROTTLE_REQUEST_SUBMIT` | `'10/min'` |  |
| `THROTTLE_SOCIAL_LOGIN` | `'10/min'` |  |
| `THROTTLE_SOCIAL_NONCE` | `'10/min'` |  |
| `THROTTLE_TELEGRAM_WEBHOOK` | `'60/min'` |  |
| `THROTTLE_TENANT_MIGRATION_READ` | `'120/min'` |  |
| `THROTTLE_TENANT_MIGRATION_WRITE` | `'30/hour'` |  |

