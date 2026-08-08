# Space Works — Advanced configuration

Optional configuration for operators. None of this is needed for a standard self-hosted install —
the [Quick start](../README.md#quick-start-run-it) covers the common case. See
[docs/self-hosting.md](../docs/self-hosting.md) for the full environment reference.

## Telegram alerts & accept/reject callbacks

Set the group chat ID + bot token in the staff `API clients → Integration settings` panel; set
`TELEGRAM_WEBHOOK_SECRET` for webhook callbacks. The bot token is encrypted at rest with
`API_CLIENT_ENC_KEY` (a Fernet key).

To post into more than one group, add **rooms** under `Settings → Notification channels → Rooms`
instead of a second bot. Every room shares the makerspace's bot: Telegram delivers all button
presses to one registered webhook authenticated by the single `TELEGRAM_WEBHOOK_SECRET`, so a second
bot's callbacks could not be authenticated or routed — its accept/reject buttons would be dead.
Adding one bot to several groups is the normal Telegram flow and costs nothing.

## Chat rooms and stored credentials

`Settings → Notification channels → Rooms` holds one row per Slack/Mattermost/Discord/Telegram
destination, each with its own encrypted credential and optional machine/type/category narrowing.
Two operational notes:

- **The legacy single webhook still works.** A makerspace with no rooms keeps resolving through the
  `Makerspace.*_webhook_url` / `telegram_group_chat_id` columns, and the upgrade migration turns each
  configured one into a room labelled `Main`. Those columns are retained for a release so a rollback
  has something to fall back to.
- **Uninstall hides, purge destroys.** Uninstalling a channel module stops delivery and keeps the
  credential; `python manage.py purge_module_data discord` deletes that channel's rooms and their
  stored secrets. Delivery history survives either way — the log keeps the room's name after the room
  is gone, so a past failure stays attributable.

`Settings → Integration health` reports every room: whether a credential is stored, when it last
delivered, and its last error. It is the only place a revoked webhook becomes visible.

## Server-to-server HMAC clients

Optional signed API access for backend integrations (disabled unless `HMAC_CLIENT_ID` + `HMAC_SECRET`
are set). Browser frontends must use publishable keys + `/api/v1/bootstrap`, never HMAC secrets.

## Security hardening

django-axes admin-login lockout, login + public-submit throttles, honeypot, and TLS headers
(`ENABLE_HTTPS`). A `pip-audit` CI job guards dependencies.

## Managed-Postgres / Supabase mode

`MANAGED_POSTGRES`, `STORAGE_PRESIGN_METHOD`, `CONN_MAX_AGE`, `DISABLE_SERVER_SIDE_CURSORS`,
`CRON_SECRET` (all default to self-hosted behavior). See
[docs/supabase-deployment.md](../docs/supabase-deployment.md).

## Scheduled return reminders

Run `manage.py send_return_reminders` from cron, or (when you can't schedule a command, e.g. on
Supabase) `POST /api/v1/internal/cron/return-reminders` with an `X-Cron-Secret` header; the endpoint
404s until `CRON_SECRET` is set.
