# Milestone 2 implementation report

> Historical record. Reviewed 2 October 2026: implementation status, permissions, addresses and test counts below refer to the original delivery, not the current deployment. Start with the [current documentation index](README.md). For recovery use [the current guide](worker-preparation-recovery.md); do not replay old reset instructions against a new attempt.

Historical delivery report. The [approved client architecture revision](client-architecture-report.md) supersedes the source-model and work-order entry details below.

Milestone 2 is complete. Milestone 3 has not started. No new packages were
installed, no existing user credentials were changed, and no network, firewall,
VM, PAD, or allowed-host settings were changed. No server was launched during
this milestone. Tests use isolated fake data; no demo work orders or agent
credentials were inserted into the local application database.

## Files created or modified

| Area | Files |
| --- | --- |
| Work orders, modified | `workorders/models.py`, `workorders/admin.py`, `workorders/tests.py` |
| Work orders, new | `workorders/services.py`, `workorders/statuses.py`, `workorders/validators.py`, `workorders/reference_data/__init__.py`, `workorders/reference_data/atc_2551qv2018.py`, `workorders/migrations/0001_initial.py` |
| Audit, modified | `audit/models.py`, `audit/admin.py`, `audit/tests.py` |
| Audit, new | `audit/migrations/0001_initial.py` |
| Agents, modified | `automation_api/models.py`, `automation_api/admin.py`, `automation_api/tests.py` |
| Agents, new | `automation_api/services.py`, `automation_api/migrations/0001_initial.py` |
| Documentation, modified | `README.md`, `docs/architecture.md` |
| Documentation, new | `docs/milestone-2-report.md` |
| Local ignored state | `db.sqlite3`, updated by migrations |

## Migrations

Created and applied successfully:

- `workorders.0001_initial`: WorkOrder and seven database check constraints.
- `automation_api.0001_initial`: Agent and unique token digest/name fields.
- `audit.0001_initial`: AuditEvent, protected foreign keys, exactly-one-subject constraint.

Only these new initial migrations were applied to the existing database. Built-in
Django users, groups, and other tables were preserved. No custom role groups or
additional accounts were created.

## Model and service design

**WorkOrder** includes the handoff's taxpayer, filing, identity, status, version,
file metadata, approval metadata, and lease/result placeholder fields. UUID is
the primary key. The unique display ID is `WO-<creation-year>-<UUID hex>`; it is
not a sequential counter. This avoids a fragile read-maximum/increment operation
on SQLite. The creator and timestamps are supplied by the service, not editable
form inputs. Timestamps are timezone-aware under `Asia/Manila`.

`create_work_order`, `edit_work_order`, and `transition_work_order` are the write
entry points. They require an active authenticated actor with the corresponding
Django add/change permission, validate the record, and write audit events in the
same transaction. Updates compare the caller's expected version in the SQL write
and increment it; stale edits fail. No-op normalized edits do not increment the
version or create a misleading audit entry. Direct model saves, queryset updates,
bulk writes, and deletion are blocked through the normal model interface.

Source fields are explicitly allowlisted in the service. Callers cannot provide
status, generated IDs/names, creator, approvals, VM paths, PDF metadata, or leases
as editable values. Future file/approval/result/lease fields must remain empty in
this milestone; they are not exposed in admin. The saved XML filename is derived
from the source fields. The VM-local XML path remains metadata: Django never
opens a VM drive or attempts to verify file existence there.

**AuditEvent** stores the actor, timestamp, event kind, work order or agent,
old/new status, and changed field names. It does not duplicate taxpayer values,
token values, or token hashes. Normal updates and deletes are blocked, including
bulk operations. Protected foreign keys preserve the linked user and subject.
Audit failure rolls back the associated work-order/agent operation.

**Agent** stores a unique name and UUID, active flag, timestamps, and only a
SHA-256 digest of a generated 64-byte random token. Local service functions
create agents, rotate tokens, and disable agents. Raw tokens are returned once to
the caller and are never logged or persisted. Token comparisons use constant-time
comparison. Rotation invalidates the prior token; disabled agents reject tokens.
No token was generated for an actual worker during implementation. These are
local model/service primitives, not an API authentication endpoint.

## Validation and normalization

- TIN1/TIN2/TIN3 require exactly three ASCII digits each; TIN4 requires five.
  Text storage and strict anchors preserve zeros and reject separators, Unicode
  digits, and trailing newlines. `combined_tin` concatenates the 14 digits.
- RDO trims surrounding whitespace, uppercases letters, and requires exactly
  three ASCII alphanumeric characters. `53a` becomes `53A`; `047` remains `047`.
  No official registration lookup or incomplete RDO code list is used.
- ATC trims/uppercases and supports `PT010`, `pt010`, and `pt 010` as `PT 010`.
  It requires `PT ` followed by three ASCII digits, then checks the one dedicated
  VM-verified 2551Qv2018 allowlist. Blank, dash, and `PT 999` are rejected.
  The model has no ATC default, and ATC is never inferred from another field.
- Only `2551Q`, `2551Qv2018`, and `BIR Form 2551Qv2018` are accepted for the
  corresponding form fields. Calendar-year must be true and year-end month `12`.
  Filing year is four-digit text, excluding year `0000`; quarter is 1 through 4.
- Required source text rejects null, empty, and whitespace-only values. Email
  uses Django's email format validation. ZIP and phone remain text; no new
  business-specific format restrictions were invented for them.
- `expected_return_period`, `expected_saved_return_name`, `expected_xml_filename`,
  and review PDF names are derived rather than accepted from callers.
- Windows-safe client names replace invalid/control characters, handle reserved
  device names, and remove trailing dots/spaces. Filename components are bounded.
- Normalization runs before field validators. Model `clean()` applies cross-field
  scope/status rules, and service saves call `full_clean()`.
- Database constraints independently enforce quarter, current form/calendar
  scope, enabled statuses, zero-filing confirmation for ready status, disabled
  submission approval, nonempty ATC, and a positive version. Other format and
  allowlist validation runs at the model/service boundary.

## Status rules

All 21 status codes in the handoff are defined without renaming them. The current
service and database enable only the following behavior:

| Operation | Rule |
| --- | --- |
| Create | Always `DRAFT` |
| `DRAFT` to `READY_TO_PREPARE` | Valid complete source data plus explicit `zero_filing_approved=True` |
| `READY_TO_PREPARE` to `DRAFT` | Allowed through the transition service |
| Edit a ready order | Any actual source change returns it to `DRAFT`; mark ready again explicitly |
| No-op edit | Keeps status/version; no redundant audit event |
| Same-state, unknown, preparation, approval, submission, or terminal transition | Rejected |

Ready is a database queue marker only. It neither launches PAD nor transmits any
data. `AWAITING_SUBMISSION_APPROVAL` cannot currently be reached. Later work must
require both the protected prepared PDF and recorded saved XML result before
enabling that transition. Future approval must bind to the exact PDF hash and be
invalidated by filing-critical changes. No approval or submission is enabled now.

## Django admin

- **Work orders:** create/edit source fields; list/search/filter; view derived
  identifiers and version. Creator is set to the signed-in user. Status and other
  protected fields cannot be typed into the form. Actions use the status service.
- **Audit events:** read-only inspection; no add, edit, or delete actions.
- **Agents:** read-only registry; token and hash are hidden. Provisioning/revocation
  is available to trusted local code through the services, not through an admin
  token-entry form. Operator-facing credential management is deferred.
- Deletion is disabled for these models. Existing Django authentication/admin
  permissions are used; Preparer/Approver/Administrator groups await Milestone 3.
- Admin edits include an expected-version value. A stale form is rejected; a
  validation conflict during the write returns a safe HTTP 409 response.

## Commands and results

Executed in PowerShell from the repository root:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations workorders automation_api audit
.\.venv\Scripts\python.exe manage.py test --verbosity 2
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py showmigrations workorders automation_api audit
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m pip check
git check-ignore .env .venv/pyvenv.cfg db.sqlite3 media/example.pdf generated/example.xml taxpayer_data/example.txt secrets/token.txt
git status --short
```

The full test command ran twice: the initial 49 tests passed; after expanding
required-field validation to reject whitespace/null values, all 49 passed again.
The final run took 2.833 seconds. This is 45 Milestone 2 tests plus the four
foundation tests. Parameterized subtests also cover every one of the 22 ATCs and
the required valid/invalid identifier cases. Test database creation and migration
from scratch succeeded; that database was destroyed afterward.

Django checks: zero issues. Migration drift: no changes detected. All three new
migrations show `[X]`. Dependency checks: no broken requirements. Git exclusions
for environment, database, documents, generated output, and secrets pass.

## Manual verification

Start or restart your local server (Ctrl+C first if it is already running in the
same terminal):

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

Open `http://127.0.0.1:8001/admin/` and sign in with your existing superuser. On a
fresh installation, create one with `manage.py createsuperuser` using the `.venv`
Python executable. Do not enter real taxpayer data during these checks.

1. Open **Work orders > Add**. Use the following fake data; leave client ID blank.

   | Field | Fake value |
   | --- | --- |
   | Client name / registered name | `FAKE TEST COMPANY` |
   | TIN1 / TIN2 / TIN3 / TIN4 | `001` / `002` / `003` / `00000` |
   | RDO | `53a` |
   | Registered address | `FAKE ADDRESS` |
   | ZIP / telephone | `0001` / `00000000000` |
   | Email | `fake@example.invalid` |
   | Line of business | `TEST ONLY` |
   | Filing year / quarter | `2026` / `3` |
   | ATC | `pt010` |

2. Keep the form defaults, Calendar year checked, and Year end month `12`.
   Leave Zero filing approved unchecked and save. The order should be `DRAFT`.
3. Reopen it. RDO should read `53A`, ATC `PT 010`, and TIN zeros should remain.
   Expected return period should be `122026Q3`; the expected saved-return name
   should be `00100200300000-2551Qv2018-122026Q3`.
4. Try ATC `PT 999`, dash, or blank, RDO `47`, or a short TIN segment. Each save
   should show validation errors. Restore the valid fake values.
5. On the list, select the order and run **Mark ready to prepare** while Zero
   filing approved is unchecked. It should report an error and stay `DRAFT`.
6. Edit it, check **Zero filing approved**, save, then run **Mark ready to prepare**
   again. Status becomes `READY_TO_PREPARE`. Nothing is sent to PAD.
7. Change the filing quarter to `4` and save. Status returns to `DRAFT`, the version
   increases, and derived return names update to `122026Q4`.
8. Open **Audit events**. Inspect creation, edit, and status entries with the actor,
   time, and changed field names. The event itself must not be editable/deletable.
9. The Agents registry is initially empty and read-only. There are no PDF upload,
   approval, submission, or lease controls.

## Git status

The repository still has no commits or remote. All project files, including
Milestone 1 files, remain untracked (`??`); nothing was staged or committed.
The local database, `.env`, and `.venv` remain ignored. Consequently, ordinary
`git diff` is not a complete review of these new files; inspect the files directly.

## Remaining questions and risks

- No unresolved validation question blocks Milestone 2. The ATC list is the exact
  user-supplied VM list, not a tax-code selection recommendation.
- The current field/form rules and database constraints deliberately limit the
  prototype. Enabling future statuses/forms requires an explicit service change,
  prerequisites, tests, and migrations; changing an enum alone is insufficient.
- SQLite write contention can produce a lock error. Version checks reject stale
  writes but are not a claim that future double-leasing tests have been completed.
  Lease/priority/retry/worker-affinity design remains Milestone 5.
- Append-only safeguards protect normal application operations, not a person
  with direct database/filesystem access or arbitrary trusted Python execution.
- Agent token checking must use a freshly loaded Agent record when a future API
  is added, so revocation/rotation takes effect immediately. Secure worker token
  provisioning, API authentication, and rate limiting remain integration work.
- Email format is currently strict. The handoff's administrator-approved legacy
  email exception needs its own audited permission/workflow design later.
- No PDF upload, PDF hash calculation, approval action, PAD launch, network API,
  AI extraction, or BIR submission is implemented. The existing PAD flows were
  not changed. The final Submit / Final Copy action remains outside this app.

## Exact test identifiers

The following tests were discovered by `manage.py test --verbosity 2`:

- `audit.tests.AuditTests.test_append_only`
- `audit.tests.AuditTests.test_existing_id_cannot_be_overwritten`
- `audit.tests.AuditTests.test_field_names_logged_without_taxpayer_values`
- `audit.tests.AuditTests.test_event_requires_subject_and_field_name_list`
- `audit.tests.AuditTests.test_admin_read_only`
- `automation_api.tests.AgentTests.test_token_is_generated_and_only_hash_is_stored`
- `automation_api.tests.AgentTests.test_rotation_revokes_old_token`
- `automation_api.tests.AgentTests.test_disabled_agent_rejects_token_and_rotation_does_not_reenable`
- `automation_api.tests.AgentTests.test_agent_permissions`
- `automation_api.tests.AgentTests.test_audit_failure_rolls_back_agent_creation_and_rotation`
- `automation_api.tests.AgentTests.test_duplicate_and_blank_names_are_rejected`
- `automation_api.tests.AgentTests.test_direct_writes_and_deletion_are_blocked`
- `automation_api.tests.AgentTests.test_admin_read_only_and_token_hash_hidden`
- `workorders.tests.WorkOrderTests.test_every_allowlisted_atc_is_accepted`
- `workorders.tests.WorkOrderTests.test_atc_normalization`
- `workorders.tests.WorkOrderTests.test_atc_rejects_blank_dash_and_unlisted`
- `workorders.tests.WorkOrderTests.test_no_atc_default_or_inference`
- `workorders.tests.WorkOrderTests.test_leading_zeros_survive_database_roundtrip`
- `workorders.tests.WorkOrderTests.test_tin_formats`
- `workorders.tests.WorkOrderTests.test_rdo_numeric_and_alphanumeric_normalization`
- `workorders.tests.WorkOrderTests.test_invalid_rdo`
- `workorders.tests.WorkOrderTests.test_structural_rdo_not_registration_verification`
- `workorders.tests.WorkOrderTests.test_filing_scope`
- `workorders.tests.WorkOrderTests.test_required_source_fields`
- `workorders.tests.WorkOrderTests.test_derived_values_match_handoff`
- `workorders.tests.WorkOrderTests.test_caller_cannot_override_derived_or_protected_fields`
- `workorders.tests.WorkOrderTests.test_safe_windows_names`
- `workorders.tests.WorkOrderTests.test_creation_is_audited_and_ids_are_unique`
- `workorders.tests.WorkOrderTests.test_ready_requires_zero_confirmation`
- `workorders.tests.WorkOrderTests.test_allowed_transitions`
- `workorders.tests.WorkOrderTests.test_future_unknown_and_same_state_transitions_are_blocked`
- `workorders.tests.WorkOrderTests.test_editing_ready_order_returns_to_draft`
- `workorders.tests.WorkOrderTests.test_normalized_noop_edit_does_not_increment_version`
- `workorders.tests.WorkOrderTests.test_stale_edits_and_transitions_rejected`
- `workorders.tests.WorkOrderTests.test_audit_failure_rolls_back_creation_and_transition`
- `workorders.tests.WorkOrderTests.test_permissions`
- `workorders.tests.WorkOrderTests.test_direct_and_bulk_writes_are_blocked`
- `workorders.tests.WorkOrderTests.test_database_constraints_even_when_bypassing_services`
- `workorders.tests.WorkOrderTests.test_model_cross_field_and_future_metadata_validation`
- `workorders.tests.WorkOrderAdminTests.test_admin_create_and_edit_use_services`
- `workorders.tests.WorkOrderAdminTests.test_admin_stale_edit_rejected`
- `workorders.tests.WorkOrderAdminTests.test_admin_invalid_atc_and_missing_atc_show_validation_errors`
- `workorders.tests.WorkOrderAdminTests.test_admin_actions_and_protected_fields`
- `workorders.tests.WorkOrderAdminTests.test_admin_anonymous_access_redirects`
- `workorders.tests.WorkOrderAdminTests.test_admin_deletion_disabled`
- `config.tests.FoundationTests.test_local_configuration`
- `config.tests.FoundationTests.test_media_has_no_public_route`
- `config.tests.FoundationTests.test_anonymous_media_request_returns_not_found`
- `config.tests.FoundationTests.test_nonlocal_host_is_rejected`
