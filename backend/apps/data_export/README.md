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

**What `REDACTED` redacts, stated positively — the name invites the wrong inference.** It redacts
**audit metadata and free-text custom-form answers**; it does **not** redact member PII. Every field
that is not explicitly dispositioned falls through to `Emitted()` (`fields.py:139`), and that includes
the scoped-PII mapped fields — the requester and attendee names, emails and phone numbers stored on
makerspace-owned rows (`encryption/registry.py` covers `HardwareRequest`, `EventRegistration`,
`Booking`, `MachineServiceRequest`, `MachineUsageEntry`, `EmailLog`). Phase 4's projection decrypts
them and writes plaintext into the archive. That is deliberate, shipped and tested — a Space Manager
exporting their own makerspace's records is entitled to the contact details members gave them — but
"REDACTED" must never be read as "PII-free".

The one PII narrowing that IS real: the **global-user closure** emits only `id` and `username`, so
platform account email and phone do not travel at this fidelity. That is what distinguishes it from
`PORTABLE`, which emits them.

At `REDACTED`, every audit `meta` object is replaced and the five operator-authored
JSON configuration fields are omitted. At `PORTABLE`, the delta-chain contract keeps
those configuration values for migration, while deployment credentials remain
omitted at both fidelities.
