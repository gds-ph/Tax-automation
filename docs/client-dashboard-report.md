# Client-first dashboard update

Historical dashboard delivery report. The [Stage 1 API update](worker-api-report.md)
supersedes references below to the API not yet being built; VM connectivity remains pending.

Implemented the requested simpler flow:
Clients → select client → configured forms → period and zero-filing confirmation
→ Queue preparation → task status. Root, login landing and the former `/filings/`
entry point all open Clients. Existing detailed work-order screens remain accessible.
Django admin is labeled Advanced settings and is unnecessary for this daily flow.

Only the client's active configured forms appear. Preparation-capable forms sort
first. Planned 1701Q remains visible with a disabled Not yet automated action.
2551Q preparation uses the selected profile from the URL, never a submitted
replacement client/form identity. The quarter and zero confirmation require user
selection; an ATC appears automatically only when explicitly configured on that
profile. All existing form-specific validation and snapshot guards still apply.

## Queue behavior

Creation and the transition to READY_TO_PREPARE share one transaction: failures
leave no orphan draft or snapshot. Signed, expiring request tokens bind the actor,
profile and displayed source versions. Configuration changes require fresh review.
A unique request UUID makes retries of the same submission return the same task
without creating or requeuing another. This does not prohibit intentionally
creating separate work orders for the same filing period from different forms.

The new nullable unique field is `WorkOrder.creation_request_id`, applied through
`workorders.0004_workorder_creation_request_id`. Existing work orders are preserved.
CSRF, authentication, role permissions and no-cache protections cover the new pages.

## Actual Power Automate execution is still pending

The dashboard queues locally and explicitly says the worker is not connected.
No request is sent to PAD and no execution is represented as running. Under the
approved architecture PAD must poll an internal Django API from inside its VM;
Django does not launch PAD or access VM-local drive paths. VM access and existing
PAD flow details have been requested to complete that connection. No API, LAN,
firewall or allowed-host changes were made, and submission stays disabled.

## Changed files

- Added `workorders/client_views.py` and `workorders/test_client_navigation.py`.
- Added templates: `clients.html`, `client_detail.html`, `prepare.html`, and
  `preparation_unavailable.html` under `templates/workorders/`.
- Added `workorders/migrations/0004_workorder_creation_request_id.py`.
- Updated `workorders/models.py`, `services.py`, `urls.py`, `test_dashboard.py`.
- Updated `config/settings.py` login destination and `accounts/test_dashboard_auth.py`.
- Updated `templates/base.html`, `templates/workorders/detail.html`, `static/dashboard.css`.
- Updated README and the historical architecture report; added this report.

## Verification

Executed with `.venv` Python only:

```powershell
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 1
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Final suite: 97 tests passed in 10.345 seconds. New coverage includes client search,
client/profile isolation, disabled planned forms, transactional queue rollback,
duplicate submission, forged tokens, stale configuration, permission checks,
CSRF and absence of GET side effects. System checks pass and no migration changes
remain. The one new migration applied successfully.

Visual verification used local rendered pages with the explicitly fake client,
in a separate headless Edge profile after the in-app browser connection failed.
Checked desktop client list/form cards and the preparation page at 600px width.
No dummy task was queued in the real local database during verification.

Manual check: refresh `http://127.0.0.1:8001/`, select FAKE DEMO CLIENT, click
Prepare 2551Q, choose a quarter, review ATC and zero status, and Queue preparation.
The resulting task must say queued locally, not running in the VM. The 1701Q
button remains disabled. Retry the same submitted form to verify it opens the
same task rather than creating a duplicate.

Git remains uncommitted on `master`; source files remain untracked. Secrets,
SQLite data, backups and media remain ignored. No packages were installed.
