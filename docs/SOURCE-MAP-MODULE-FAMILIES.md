# Module families and public-site settings

`makerspaces/capability_definitions_modules.py` adds the default-on `loans.enabled`
feature through the capability-definition barrel. `loan_visibility.py` names the
frontend loan modules and dependent features; `platform.bootstrap_payload` suppresses
their public advertisement while retaining all installed modules and domain rows.
Retained-loan policies and charge/payment capabilities remain independent, so hiding
loans cannot lose late fees or strand outstanding debt.

`makerspaces/models_makerspace.py` explicitly re-exports the tenant root from
`models_makerspace_core.py`; the abstract `models_public_site.PublicSiteSettings`
owns catalogue/site publication flags and the optional public-home preference.
`public_site.py` is the public catalogue gate. `bookings/access.py` applies active
account identity and any existing membership's waiver obligations.
`machines/low_stock.py` rechecks procurement under the makerspace lock before its
cross-app create, serializing it with module uninstall.

`inventory/middleware.py` preserves the public authentication imports through explicit
exports from `middleware_hmac.py`. Browser publishable-key validation lives in
`middleware_publishable.py`, where it follows public-site publication independently
of the catalogue flag.

`hardware_requests/public_views.py` re-exports request submission from
`public_request_views.py` and retained public-token status reads from
`public_status_views.py`. The creation workflow rechecks the loans switch under its
makerspace lock.

`operations/views_dashboard_counts.py` explicitly re-exports the serializer in
`serializers_dashboard.py` and aggregation in `dashboard_counts.py`. Optional event
and booking queries live in `dashboard_programmes.py`; all counter failures log tenant
context and error class without exception text or tracebacks that could carry PII.
The API resolves makerspace authority through RBAC before aggregation; each staff
row queryset also passes through RBAC. Mixed machine/programme roles retain their
programme queues while machine row scoping stays in force. Finance grants keep
core debt counters with the rail off; email counters require settings authority.
Programme counter
failures are isolated by family.

`data_export/classification_modules.py` extends the reviewed makerspace field list.
`tenant_migration/tenant_dump_modules.py` declares the new publication fields as
preserved preferences, with no target reset; target module/feature gates remain
authoritative. No model or User FK is added.

Frontend `lib/publicHome.ts` selects an available family from bootstrap. `AppRoutes`
loads the selected page lazily and registers both event-detail URL forms.
`MakerspacePublicSiteSettings` edits publication/home through the existing audited
makerspace PATCH and invalidates settings and bootstrap server-state caches,
including the member portal's separate bootstrap key. Machine warranties remain
reachable with loans disabled because they belong to the machine family.
`staff/staffAccess.ts` admits event, booking, member and finance custom staff to
the dashboard, independently of inventory actions.
