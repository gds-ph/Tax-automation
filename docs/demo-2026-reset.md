# ABC TEST COMPANY 2026 prototype reset

> Historical record. Reviewed 2 October 2026: implementation status, permissions, addresses and test counts below refer to the original delivery, not the current deployment. Start with the [current documentation index](README.md). For recovery use [the current guide](worker-preparation-recovery.md); do not replay old reset instructions against a new attempt.

User requested a fresh Q1-Q4 run and confirmed desktop flows stopped and eBIRForms
closed. Scope: DUMMY-CLIENT-001, TIN 65070331200000, 2551Qv2018, year 2026.

Dashboard: six existing work orders archived; zero active scoped orders and no
running attempts remain. The successful Q1, Q2 and Q4 PDF copies remain protected
in Django storage. Immutable snapshots, worker outcomes and audit history were
retained; each archive operation adds a human audit event. Client/profile and
credentials are unchanged. No fresh tasks were automatically queued.

Migration workorders.0007_workorder_archive adds is_archived. Archived records
are excluded from current work lists, worker claims and XML reservations, and
cannot be edited/requeued through services. Detail links retain history and show
an archive notice. Ready orders are returned to draft when archived; successful
historical outcomes are not rewritten as failures. Administrator access can
still locate retained records. No public archive/reset HTTP endpoint was added.

SQLite backup: ignored backups/before_2026_demo_reset.sqlite3. This is a local
pre-reset backup, not a file to copy into the VM or commit to Git.

VM step remains manual: copy worker/Reset-Demo2026.ps1 to C:\TaxAutomation and
run with both flows stopped and eBIRForms closed. It archives exactly the four
named XML files, six known work-order output directories, and matching top-level
ABC_TEST_COMPANY_2551Q_2026_Q1-Q4 PDFs. It preserves the journal last, refuses a
journal from a different job and does not modify worker.json or the eBIRForms
profile. Archive folders are private, unique and retained under the VM user's
LOCALAPPDATA\TaxAutomationWorker\archive directory. It does not claim tasks or
launch eBIRForms. Run this one-off script before creating any new tasks.

Validation: 40 targeted tests passed; full `manage.py test --noinput --verbosity 0`
passed all 126 tests in 31.017 seconds. Django checks and migration drift check
passed. PowerShell parser passed; the VM cleanup has not been executed by Codex.
Live read-only verification found six archived/zero active scoped orders, zero
running attempts, no remaining XML reservations, and three retained PDF copies.

## Temporary dashboard reset button

ABC TEST COMPANY's client page now has Reset 2026 test filings, visible only to
superusers and restricted server-side to the exact configured fake client code,
registered name and TIN. Other taxpayers and filing years are outside its scope.
GET is read-only. POST requires CSRF, two explicit confirmations, and a signed
15-minute actor/client/order-version token. New or changed orders invalidate the
confirmation. Confirmed stopped attempts are abandoned and archived atomically.
The response downloads a freshly generated Reset-Demo2026.ps1 with current IDs.
No worker token is included and no VM file is touched by Django. The user must
run the downloaded script inside the VM before queuing fresh work. The page
explains this remaining step, so the button does not claim one-click VM cleanup.
Generated scripts have a completion marker to prevent accidental successful reruns.
Historical protected PDF copies remain accessible by authorized users.

Git remains untracked as before; no commit, staging, or push performed.
