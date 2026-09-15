# Milestone 3 implementation report

Historical delivery report. The [approved client architecture revision](client-architecture-report.md) supersedes the source-model and work-order entry details below.

Milestone 3 adds the everyday office dashboard. Milestone 4 has not started.

## Delivered behavior

- Sign in at `/login/` with an existing Django account, including the existing
  superuser. Sign out through a CSRF-protected POST button; GET logout is rejected.
- `/` and `/filings/` display Filing Types, initially with **2551Q â€” Quarterly
  Percentage Tax Return**, January 2018 version. Summary counts show draft and
  ready work orders. No unsupported filing type is offered.
- Select 2551Q to list its work orders or create a new one. The selected workflow
  supplies form code/version and calendar-year settings on the server. Posted
  hidden values cannot override these or alter protected status/approval fields.
- List filters support client name/reference, status, filing year, and quarter.
  Invalid filters display errors. Pagination keeps the filters; each page holds
  at most 20 orders.
- Create/edit forms retain the Milestone 2 validators, normalize RDO/ATC input,
  preserve leading zeros, and leave ATC and zero-filing confirmation unselected.
  The ATC suggestions come from the existing dedicated 22-code list.
- Detail pages show client and filing information, exact derived saved-return
  filename, current status/version, and paginated activity history.
- Mark ready / return to draft use the existing transactional status service,
  expected version, and audit recording. They accept POST only. Editing a ready
  order returns it to draft; a stale form cannot overwrite a newer version.
- Validation and SQLite lock conflicts show recoverable messages. Dashboard
  responses use no-cache/no-store headers. Django template escaping and CSRF
  middleware remain enabled.
- The UI uses local templates and CSS, with desktop and narrow-screen layouts,
  visible field labels, focus styles, a skip link, validation messages, and empty
  states. There are no external fonts, CDNs, or JavaScript framework dependencies.

## Permission policy

| Group | Read work orders | Read history | Create/edit/mark ready | Agent registry |
| --- | --- | --- | --- | --- |
| Preparer | Yes | Yes | Yes | No |
| Approver | Yes | Yes | No | No |
| Administrator | Yes | Yes | Yes | View permission |

Roles use Django model permissions rather than only hiding buttons. Access is
checked before querying work orders. All current authorized office users share
the list; no client/owner-specific data partitions were specified or added.

No approval permissions or actions are enabled yet. Group membership is additive:
an account in both Preparer and Approver can prepare because it has Preparer
permissions. The Administrator group does not grant `is_staff`, `is_superuser`,
user-management, deletion, or token-management privileges. Existing superusers
retain access; assigning staff status for Django admin is a separate deliberate
account setting. Regular dashboard users do not need it.

The data migration initializes the three named groups with the listed permissions.
It does not assign users to them or create accounts. A rerun is idempotent and
does not elevate users. Its reverse preserves group memberships rather than
deleting them.

## Files created or modified

| Area | Files |
| --- | --- |
| Configuration, modified | `config/settings.py`, `config/urls.py` |
| Accounts, modified | `accounts/views.py` |
| Accounts, new | `accounts/migrations/0001_dashboard_roles.py`, `accounts/test_dashboard_auth.py` |
| Work orders, modified | `workorders/views.py` |
| Work orders, new | `workorders/filing_types.py`, `workorders/forms.py`, `workorders/urls.py`, `workorders/test_dashboard.py` |
| Optional fake samples, new | `workorders/management/__init__.py`, `workorders/management/commands/__init__.py`, `workorders/management/commands/seed_demo.py` |
| Templates, new | `templates/base.html`, `templates/registration/login.html`, `templates/403.html`, `templates/404.html` |
| Work-order templates, new | `templates/workorders/filing_types.html`, `list.html`, `form.html`, `detail.html`, `field.html`, `status.html` |
| Local styling, new | `static/dashboard.css` |
| Documentation | Modified `README.md`; added `docs/milestone-3-report.md` |
| Ignored local state | `db.sqlite3`, updated by the role data migration |

Existing WorkOrder, AuditEvent, and Agent model schemas and status-service rules
were retained. No dependency installation or requirements change was needed.

## Migration and commands

Created and applied **`accounts.0001_dashboard_roles`**. This is a data migration
creating/configuring the named groups and their current model permissions.

Executed from PowerShell in the repository:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test --verbosity 1
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py showmigrations accounts
.\.venv\Scripts\python.exe -m pip check
git status --short
```

Local read-only inspection also checked Git status, source files, loopback
listeners, and availability of an installed browser. Python scripts rendered
fake-data previews into a temporary directory and performed local HTTP checks.
No VM files, unrelated processes, firewall rules, or network settings were changed.

## Test and visual verification

The regression suite initially passed all 49 existing tests. The expanded suite
contains **78 tests** (29 new dashboard/role/demo tests plus the original 49).
An initial role-migration idempotency test attempted to open SQLite's schema
editor inside a test transaction and failed. The test was corrected to provide
the connection alias directly, because this data migration performs no DDL.
The expanded suite then passed in full.

New coverage includes:

- Exact group permission sets, idempotent setup, and no automatic staff/superuser elevation.
- Login, invalid/inactive login, safe local `next` redirects, rejection of external
  redirect targets, POST-only logout, and CSRF checks on login/logout.
- Login/permission requirements on dashboard pages; read-only Approver access;
  unassigned-user rejection; Administrator creation without superuser status.
- Fixed 2551Q source fields despite forged POST fields, ATC/zero confirmation
  left unset, validation errors retaining submitted values, normalized identifiers.
- Audited creation/editing, derived filenames, ready/draft transitions, removal
  of zero confirmation during an edit, stale forms, and recoverable write conflicts.
- CSRF enforcement on every work-order mutation.
- Combined filters, invalid filters, empty results, pagination, no-store headers,
  escaping of client text, and separate audit-history permission.
- Unsupported filing types and future API/PDF/approval routes remain unavailable.
- Optional fake demo command is idempotent and rejects unauthorized actors.

Django system checks report zero issues; migration drift reports no changes;
the role migration shows applied; dependency checks report no broken requirements.

Live HTTP checks on the already-running `127.0.0.1:8001` server verified:

| Path | Unauthenticated result |
| --- | --- |
| `/login/` | 200, new dashboard login page |
| `/static/dashboard.css` | 200 |
| `/filings/`, `/work-orders/` | 302 to login with a local next target |
| `/media/example.pdf` | 404 |
| `/api/agent/next-preparation/` | 404 |

The in-app browser connector failed before browser execution. Visual review used
the installed Edge browser in a separate hidden headless process instead, with
fresh temporary profiles and HTML rendered by Django from an isolated in-memory
database. No actual user session or taxpayer data was used. Login, Filing Types,
create, detail, and narrow-screen list previews were inspected. A table overflow
found during narrow-screen review was corrected; horizontal scrolling is confined
to the table. Browser layout verification used rendered snapshots; authenticated
interaction/security behavior was verified through the Django test client rather
than an interactive browser session.

No fake preview accounts or orders were inserted into the user's local database.
The existing development server and user accounts were left running/unchanged.

## How to verify manually

1. Start or restart the server if necessary:

   ```powershell
   .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
   ```

2. Open `http://127.0.0.1:8001/login/` and use your existing account. An existing
   superuser needs no group assignment. Select **2551Q** on **Filing types**.
3. Click **Create work order**. Use fake details such as `FAKE TEST COMPANY`, TIN
   segments `001 / 002 / 003 / 00000`, RDO `53a`, ZIP `0001`, telephone
   `00000000000`, email `fake@example.invalid`, address `FAKE ADDRESS`, and business
   `TEST ONLY`. Select year `2026`, quarter `3`, and explicitly enter ATC `pt010`.
4. Save the draft. Verify normalized RDO `53A`, ATC `PT 010`, preserved TIN zeros,
   return period `122026Q3`, and the creation entry in Activity history.
5. Try marking ready before zero filing is confirmed. It should show a clear
   error. Edit, confirm zero filing, save, then mark ready. No desktop process
   starts. Change the quarter afterward: status returns to Draft and names/history
   update. Open two edit tabs and save one before the other to check stale edits.
6. Use the work-order list to combine client/status/year/quarter filters and clear
   them again. Sign out and verify a direct work-order link redirects to login.
7. To test roles, use your superuser at `/admin/auth/user/` to create ordinary
   users and assign their Groups. A Preparer can create/edit; an Approver can view
   but cannot modify. Do not tick Staff or Superuser just to use the dashboard.

Optional: explicitly load three fake sample orders using an existing authorized
user. Replace `YOUR_USERNAME` with that username:

```powershell
.\.venv\Scripts\python.exe manage.py seed_demo --actor YOUR_USERNAME
```

This does not create credentials or overwrite existing demo references. It has
not been run against the local application database during implementation.

## Git status and remaining limits

The repository still has no commits: all project files remain untracked (`??`),
including earlier milestones. Nothing was staged or committed. `.env`, local
databases, `.venv`, and protected documents remain ignored; preview artifacts live
outside the repository in a temporary folder.

- Only calendar-year, zero-filing 2551Qv2018 is available. The filing registry is
  extensible, but adding another entry alone does not implement another workflow.
- PDF upload/review, SHA-256 approval binding, approval/rejection controls, PAD/API
  connectivity, worker leasing, AI extraction, and BIR submission remain disabled
  or unimplemented. Existing stage-specific metadata remains locked.
- Role permissions apply across the office dataset; tenant/client/owner isolation
  and separation-of-duties rules would require additional explicit requirements.
- Administrator group membership is not equivalent to Django superuser access.
  Account provisioning remains with the existing trusted Django administrator.
- SQLite concurrency limits and the Milestone 2 legacy-email exception remain
  deferred. Loopback development remains the only configured hosting mode.
- Actual Submit / Final Copy stays outside this app and disabled in PAD with fake
  data. Milestone 4 requires a separate approval to proceed.

## Exact new test identifiers

- `accounts.test_dashboard_auth.DashboardRoleTests.test_three_groups_and_permissions`
- `accounts.test_dashboard_auth.DashboardRoleTests.test_role_setup_is_idempotent_and_does_not_elevate_users`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_login_logout_and_safe_redirect`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_login_preserves_safe_local_next`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_invalid_or_inactive_login_rejected`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_login_and_logout_require_csrf`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_authenticated_login_redirects_to_filings`
- `accounts.test_dashboard_auth.DashboardAuthTests.test_unassigned_user_sees_access_guidance`
- `accounts.test_dashboard_auth.DemoCommandTests.test_seed_demo_is_opt_in_fake_and_idempotent`
- `accounts.test_dashboard_auth.DemoCommandTests.test_seed_demo_rejects_unauthorized_actor`
- `workorders.test_dashboard.DashboardTests.test_all_dashboard_pages_require_login`
- `workorders.test_dashboard.DashboardTests.test_unassigned_user_cannot_read_or_write`
- `workorders.test_dashboard.DashboardTests.test_all_roles_can_view_and_responses_are_not_cached`
- `workorders.test_dashboard.DashboardTests.test_approver_is_read_only`
- `workorders.test_dashboard.DashboardTests.test_filing_types_and_unknown_type`
- `workorders.test_dashboard.DashboardTests.test_create_is_fixed_to_selected_filing_and_audited`
- `workorders.test_dashboard.DashboardTests.test_administrator_can_create_without_becoming_superuser`
- `workorders.test_dashboard.DashboardTests.test_invalid_create_redisplays_errors_and_preserves_values`
- `workorders.test_dashboard.DashboardTests.test_atc_and_zero_confirmation_not_preselected`
- `workorders.test_dashboard.DashboardTests.test_edit_updates_derived_name_and_history`
- `workorders.test_dashboard.DashboardTests.test_editing_ready_can_remove_zero_confirmation_and_returns_draft`
- `workorders.test_dashboard.DashboardTests.test_stale_edit_rejected_without_overwriting`
- `workorders.test_dashboard.DashboardTests.test_write_conflict_and_database_lock_show_recoverable_errors`
- `workorders.test_dashboard.DashboardTests.test_ready_and_draft_are_post_only_and_version_checked`
- `workorders.test_dashboard.DashboardTests.test_all_mutations_require_csrf`
- `workorders.test_dashboard.DashboardTests.test_combined_filters_and_invalid_filters`
- `workorders.test_dashboard.DashboardTests.test_empty_state_and_pagination_preserve_filters`
- `workorders.test_dashboard.DashboardTests.test_history_requires_audit_permission_and_escapes_content`
- `workorders.test_dashboard.DashboardTests.test_future_endpoints_remain_absent`
