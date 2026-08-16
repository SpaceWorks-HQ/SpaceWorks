# Tenant export disposition registry

This package is the security contract shared by the readable `REDACTED` export and
the future `PORTABLE` migration archive. It intentionally contains no job model,
runner, API, storage code, or console.

The readable export's global-user closure emits exactly `id` and `username`.
This is a new intentional disclosure: the current staff audit API returns only the
numeric actor ID and the frontend does not show the actor. Usernames are included so
an operator can interpret actor and creator references, but they are identifying data
and can correlate the same person across exports. The portable projection is the
literal migration allowlist in `fields.py`; neither projection carries credentials,
global authority, verified identities, groups, or permissions.

At `REDACTED`, every audit `meta` object is replaced and the five operator-authored
JSON configuration fields are omitted. At `PORTABLE`, the delta-chain contract keeps
those configuration values for migration, while deployment credentials remain
omitted at both fidelities.
