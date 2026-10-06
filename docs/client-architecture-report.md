# Approved Milestone 2 client architecture revision

> Historical record. Reviewed 2 October 2026: implementation status, permissions, addresses and test counts below refer to the original delivery, not the current deployment. Start with the [current documentation index](README.md). For recovery use [the current guide](worker-preparation-recovery.md); do not replay old reset instructions against a new attempt.

Historical model-refactor report. The subsequent [client dashboard update](client-dashboard-report.md) implements the client-first navigation described as pending below.

Completed on 2026-09-14. This report covers the approved generic model refactor
and compatibility fixes to the existing dashboard. It does not deliver the later
client-list navigation or start a new dashboard/integration milestone.

## Files created or modified

New source files:
- `workorders/catalog_models.py`: Client, FormDefinition, ClientFilingProfile.
- `workorders/catalog_services.py`: audited configuration creation and updates.
- `workorders/model_support.py`: shared service-only write/deletion guards.
- `workorders/definitions/__init__.py`: explicit registry, generic period dispatch.
- `workorders/definitions/form_2551qv2018.py`: current form/version validation and naming.
- `workorders/test_support.py`: explicitly fake test fixtures.
- `workorders/test_migrations.py`: isolated forward-migration and legacy-link test.
- Four migrations listed below.
- `docs/client-architecture-report.md`: this report.

Modified source files:
- `workorders/models.py`, `services.py`, `admin.py`, `forms.py`, `views.py`,
  `filing_types.py`, `tests.py`, `test_dashboard.py`.
- `workorders/management/commands/seed_demo.py`.
- `audit/models.py`, `audit/admin.py`, `audit/tests.py`.
- `accounts/test_dashboard_auth.py`.
- `config/urls.py`, `config/settings.py`: remove unfinished Company routing and
  restore the existing filing dashboard entry point; no network settings changed.
- `templates/workorders/form.html`, `templates/workorders/detail.html`.
- `README.md`, `docs/architecture.md`, and supersession notices in the earlier
  `docs/milestone-2-report.md` and `docs/milestone-3-report.md`.

Removed only unfinished, unapplied Company work: `workorders/company_models.py`,
`company_services.py`, `company_forms.py`, `company_views.py`, `company_urls.py`,
and its unapplied WorkOrder migration. The unfinished audit migration was replaced
with the client-based version below. Applied `0001` migrations were preserved.

The existing version-specific ATC allowlist remains the single authoritative
list in `workorders/reference_data/atc_2551qv2018.py`.

## Migrations created and applied

All four applied successfully to the local SQLite database:

1. `workorders.0002_client_clientfilingprofile_formdefinition_and_more`
2. `workorders.0003_seed_definitions_preserve_legacy`
3. `accounts.0002_client_configuration_roles`
4. `audit.0002_remove_auditevent_audit_exactly_one_subject_and_more`

The schema migration renames the old textual `client_id` to
`legacy_client_reference`; it does not discard it to add the new Client FK.
New client/profile associations are nullable only for historical compatibility.
Existing rows retain their original fields, status, version, timestamps, and audit
references. The data migration creates an immutable import snapshot for each old
row and leaves it unlinked. It never guesses client types, merges taxpayers, or
silently changes a historical ready record into executable work. Imported
snapshots have no attributed human creator and explicitly identify their origin.

The local database contained zero work orders before migration. The automated
migration test supplies a fake historical ready order, verifies every old scalar
field and audit association survives, verifies it cannot route, and exercises
explicit linking into a new draft while preserving revision 1. No demo clients,
work orders, or credentials were inserted into the local database. Only the two
form definitions and permissions were seeded.

A pre-change SQLite backup was saved in the Git-ignored `backups/` directory as
`before_client_refactor_20260914_151330.sqlite3`. The preservation data migration
is intentionally irreversible; restoring a verified backup is the rollback path,
with the corresponding compatible source version. Do not downgrade by dropping
client/snapshot data.

## Models and services

- **Client:** explicit INDIVIDUAL/NON_INDIVIDUAL type; unique client code;
  reusable taxpayer fields; optional trade name and VM-local folder metadata;
  active flag, timestamps, optimistic version. All identifiers remain text.
- **FormDefinition:** form/version metadata, frequency, explicit registry key,
  preparation/submission availability, active flag and version. Form code/version
  is unique; identity cannot be reassigned through update services. Seeded 2551Q
  is preparation-capable; 1701Q is planned, with blank unconfirmed version and key.
- **ClientFilingProfile:** protected client/form references, unique pair, active
  flag, calendar/fiscal settings, nullable explicit ATC default, JSON form defaults,
  version and timestamps. Its client/form identity cannot be reassigned.
- **WorkOrder:** client/profile, year and optional month/quarter, zero-filing and
  confirmation flags, form data, status and reserved result/approval metadata.
  Services reject taxpayer-source and derived-name input on work-order writes.
- **WorkOrderSnapshot:** immutable numbered revisions, source configuration and
  versions, period/form data, canonical JSON SHA-256, actor and timestamp. Original
  flat columns are retained as read-only materialized snapshot values for legacy
  data and existing displays, not independently editable source fields.
- **AuditEvent:** append-only work-order, client, definition, profile, or agent
  subject; exactly one subject. Work-order events may link a matching snapshot.
  Changed-field logs contain names, not taxpayer values. Snapshot contents are
  protected application data and remain in the ignored database.

`catalog_services.create_record/update_record` validate, check permissions and
write audit events atomically. `services.create_work_order` requires an active
saved profile. `edit_work_order` changes only period/zero flags/form data and
creates a revision from the existing snapshot; it does not refresh live sources.
`refresh_work_order_snapshot` explicitly captures current sources, resets to
DRAFT, and clears zero confirmation. It retains the order's explicitly chosen
form data; changed profile defaults are not silently substituted into that order.

`link_legacy_work_order` requires explicit confirmation, an expected version, a
chosen profile of the same form/version, and explicit form data. It creates a new
snapshot and clears confirmation in a new draft. Historic records with reserved
result metadata remain protected against editing by current validation; handling
such completed records requires a later explicit migration policy.

Writes use atomic transactions and compare expected row versions in SQL. SQLite
lock/conflict errors require reloading; there is no worker lease or retry policy.
Public direct/bulk writes and deletion are blocked. These application guards are
not protection against someone with raw database access.

## Validation and normalization

- TIN: four text segments of exactly 3/3/3/5 ASCII digits; leading zeros retained.
  Combined TIN concatenates the segments. No registration verification claimed.
- RDO: trim and uppercase, then exactly three ASCII letters/digits. Alphanumeric
  codes such as 53A/53B/54A/54B accepted; no incomplete official list imposed.
- ATC: one version-specific 22-code allowlist. PT010/pt010/pt 010 normalize to
  PT 010. Blank, dash and PT 999 rejected. No model defaults or inference from
  taxpayer fields. A deliberately entered profile default may populate new orders;
  work-order input may override it explicitly.
- Current 2551Q: fixed 2018 identity/selection/automation key; quarterly period;
  four-digit text year other than 0000; calendar basis and year-end 12; zero filing.
  Unknown JSON keys rejected. Return names are derived by the form definition:
  `122026Q3` and `65070331200000-2551Qv2018-122026Q3` for the supplied example.
- Generic period structure accommodates monthly/annual definitions later, but
  no additional form automation or fiscal 2551Q flow exists. Planned forms accept
  empty form data until a schema is implemented and produce no executable route.
- Model clean methods enforce cross-field rules. Database constraints cover
  unique profiles/versions, valid periods, paired client/profile references,
  enabled states, confirmation, disabled submission, positive versions and audit
  subject count. Form-specific cross-table rules also require the service layer.

## Status transitions and routing

Only DRAFT → READY_TO_PREPARE and READY_TO_PREPARE → DRAFT are enabled.
Queuing requires active client/profile/form, a registered preparation definition,
valid filing data, explicit zero confirmation, a valid snapshot digest and exact
matching current source versions/values. Same-state and all later transitions
are rejected. Editing a ready order's filing details creates a revision and
returns it to draft. Normalized no-op edits do not alter status or version.

`get_preparation_automation_key` re-reads the order and checks readiness again.
Only `PREPARE_2551QV2018_ZERO` can currently be returned. Unsupported definitions,
planned 1701Q, stale snapshots, or forced availability flags cannot fall back to
2551Q. This is a service-level routing guard, not a PAD/API execution endpoint.

## Django admin and existing dashboard

Clients, definitions and profiles are registered with audited, version-checked
admin saves. No deletion is enabled. Work-order details and snapshot contents are
read-only; work-order list actions support ready, draft and explicit snapshot
refresh. Use the existing dashboard for work-order period/data edits. Snapshot
and audit admin pages cannot be changed or deleted.

Preparer receives Client/Profile add/change plus configuration/snapshot viewing.
Approver remains read-only. Administrator additionally manages definitions.
None of these groups grants Staff or superuser status. Admin access needs Staff
status separately; current office roles share records and have no per-client ACL.

The existing 2551Q creation screen now asks for an active saved filing profile,
period, zero status and ATC. It no longer repeats editable taxpayer fields.
The full Client list → applicable filings dashboard remains later work. Planned
1701Q can be configured in admin/services but cannot be queued or selected as
an executable 2551Q workflow.

## Exact verification executed

All Python commands ran through the local virtual environment:

```powershell
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 1
.\.venv\Scripts\python.exe manage.py test workorders.test_migrations --noinput --verbosity 2
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py showmigrations workorders audit accounts
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe -m pip check
```

- First regression run: 79 tests passed (8.298 seconds).
- Isolated forward-migration test: 1 passed (1.487 seconds).
- Final complete suite: **85 tests passed** (9.658 seconds), including migration,
  configuration, validators, immutable snapshots, optimistic conflicts, audit
  rollback, routing, admin, authenticated dashboard, CSRF, roles, demo idempotence,
  existing agent-token lifecycle and foundation checks. Subtests exercise all ATCs
  and multiple invalid formats.
- Four migrations applied successfully; all displayed as `[X]`.
- System check: zero issues. Migration check: no changes detected.
- Dependency check: no broken requirements. No packages installed or upgraded.
- Live loopback HTTP: `/login/` 200; anonymous `/admin/` and `/work-orders/new/`
  lead to login; `/media/example.pdf` and `/api/agent/next-preparation/` return 404.
- Existing listener remains `127.0.0.1:8001`. No network/host/firewall change.
- Templates/admin responses were exercised through Django tests. No new visual
  browser inspection was performed for this compatibility-only form revision.

## Manual verification

1. Open `http://127.0.0.1:8001/admin/` using the existing superuser.
2. Inspect Form definitions: 2551Q has `PREPARE_2551QV2018_ZERO`, preparation on,
   submission off. 1701Q has blank version/key and preparation off.
3. Add a clearly fake Client with explicit type, TIN `001`/`002`/`003`/`00000`,
   RDO `53a`, fake contact/address data and an `example.invalid` email.
4. Add an active Client filing profile for that client and 2551Q. Leave its ATC
   default blank to require explicit order input, or deliberately enter one.
5. Open `/filings/2551q/new/`. Select that profile, year 2026, Q3, zero filing,
   explicit confirmation and ATC `pt010`. Save. Verify normalized ATC PT 010,
   RDO 53A, combined TIN 00100200300000 and period 122026Q3 in details.
6. Mark ready. It records READY_TO_PREPARE only; no PAD or submission runs.
7. Change the Client's fake address in admin. The work order and its snapshot
   retain the prior address. Returning to draft and marking ready is blocked
   until refresh. On the Work orders admin list, select the order and use
   **Refresh source snapshot and clear zero-filing confirmation**. Verify the
   new address, new snapshot revision, draft status and cleared confirmation.
   Edit and confirm again through the dashboard before marking ready.
8. Add a second profile for planned 1701Q to the same client. The pair is allowed;
   a duplicate 2551Q profile is rejected. Planned 1701Q has no executable action.
9. Deactivate the 2551Q profile. It disappears from new-order choices and cannot
   be queued through services. Existing historical snapshots remain available.
10. Inspect Audit events and Work order snapshots: reads work, edits/deletes do
    not. Confirm anonymous protected routes redirect to login and media stays 404.

Optional fake fixtures, only if desired:

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo --actor YOUR_USERNAME
```

This creates three explicitly typed fake clients/profiles/orders, never accounts
or passwords, and leaves existing demo references unchanged on repeated calls.

## Git status and remaining risks

The repository remains on `master` with no commits. Application source and docs are
untracked, as before this revision; nothing was staged, committed or pushed.
`.env`, `.venv`, SQLite files, backups and protected media remain ignored. Since
there is no committed baseline, this report's changed-file list identifies the
revision relative to the inspected workspace rather than a Git diff.

Remaining decisions/work: client-centered navigation; confirmed 1701Q version,
validation and tested PAD subflow; fiscal rules for any future form; protected
PDF/result transaction and approval binding; API authentication and leasing;
queue priority/retries/heartbeat/maintenance; internal deployment networking.
Legacy client/profile linking requires explicit human review. Cross-table rules
are enforced in models/services rather than portable SQLite constraints alone.
The snapshot hash is not a signature, PDF hash, or XML/PDF equivalence proof.

VM paths remain metadata. Django never opens or serves the VM's C: drive. Actual
BIR Submit / Final Copy stays outside this application and disabled in PAD for
fake-data testing. No additional milestone was begun.
