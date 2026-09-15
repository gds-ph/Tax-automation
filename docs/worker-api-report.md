# Stage 1 worker API implementation report

Implemented locally on 2026-09-14. This completes the approved Django/API and
Windows helper work. It does not claim the Hyper-V VM is connected, the PAD
wrapper is configured, or the existing Tax-Filing flow has executed through it.
The [setup guide](worker-api-setup.md) provides the exact next steps and mappings.

## Delivered behavior

- Worker bearer authentication using existing hashed-token Agent identities.
  Sessions do not grant worker access; revoked/disabled credentials are rejected.
- Atomic FIFO claims for eligible, current-snapshot 2551Q zero filings.
  One global desktop execution slot, 30-minute lease, explicit renewal, no
  automatic retry/reassignment on expiry. Duplicate claim delivery is idempotent.
- All 20 Tax-Filing inputs mapped from frozen snapshots as text, including Q2
  rather than default Q3 and branch code leading zeros. Attempt-specific VM PDF
  output directories; exact expected XML naming under the VM savefile directory.
- Lease-owner-only PDF uploads with a 25 MiB cap, SHA-256 comparison, pypdf
  validation, generated private storage paths and idempotent identical retries.
- Exact-path Stage 1 result reporting. Upload alone leaves Processing preparation.
  Both stored PDF/hash and XML result are required before Awaiting submission
  approval; the stored hash is rechecked at completion. Conflicting retries fail.
- Human versus worker audit attribution is explicit. Audit and snapshots remain
  append-only. Claimed/completed work orders cannot be edited/refreshed into drafts.
- Protected PDF download with separate role permission, hash check, attachment
  disposition, no-store, nosniff and sandbox headers. No public media route.
- Operator provisioning/recovery commands; expired attempts remain reserved until
  the operator confirms PAD stopped. Recovery never automatically requeues a job.
- Windows PowerShell 5.1-compatible bridge for Health/Poll/Start/Publish/Renew.
  Private journal, fixed request IDs, local mutex, same-attempt output check and
  pre-execution Running marker prevent silent restart of an already-started flow.
  PDF transfer retries do not rerun Tax-Filing. No PAD/submission launch code.
- A prepared XML filename is reserved while its work order awaits review so a
  later preparation cannot silently overwrite the return needed for Stage 2.

## Files

New implementation:
- `automation_api/worker_policy.py`, `worker_services.py`, `views.py`, `urls.py`.
- `automation_api/management/__init__.py`, `management/commands/__init__.py`,
  `management/commands/provision_worker.py`, `management/commands/stop_preparation.py`.
- `automation_api/test_worker_api.py`, `automation_api/test_worker_bridge.py`.
- `worker/WorkerBridge.ps1`, `worker/worker.example.json` (placeholder only).
- Six migrations below; `docs/worker-api-setup.md` and this report.

Updated:
- `automation_api/models.py`, `automation_api/admin.py`.
- `workorders/models.py`, `services.py`, `views.py`, `urls.py`, `forms.py`,
  `client_views.py`, `test_support.py`, `test_client_navigation.py`.
- `audit/models.py`, `audit/admin.py`, `accounts/test_dashboard_auth.py`.
- `config/urls.py`, `templates/workorders/detail.html`, `templates/workorders/prepare.html`.
- `.gitignore`, `requirements.txt`, `README.md`, `docs/architecture.md`,
  `docs/client-dashboard-report.md`.

Added dependency: `pypdf==6.18.1`, installed exclusively in `.venv` and pinned.
Django remains 5.2.17. No global package or network configuration changes.

## Migrations applied

1. `workorders.0005_remove_workorder_wo_m2_enabled_statuses_and_more`
2. `workorders.0006_alter_workorder_options`
3. `accounts.0003_protected_pdf_permission`
4. `automation_api.0002_preparationattempt`
5. `audit.0003_auditevent_performed_by_agent_alter_auditevent_actor_and_more`
6. `automation_api.0003_agent_last_seen_at`

PreparationAttempt records the request UUID, work order, snapshot, agent, secret
lease token, expiry, running/completed state, unique execution slot and final
result digest. Agent last-seen reflects authenticated API contact. WorkOrder adds
the VM PDF path and permits only the implemented preparation states. Database
constraints gate the final PDF/XML state and require exactly one human/worker
audit actor. The separate PDF permission is granted to the three existing roles.

Before migration, a SQLite backup was written to ignored
`backups/before_worker_api_20260914_170412.sqlite3`. The real local database had
one READY_TO_PREPARE task before and after migration. It still has zero Agents
and zero PreparationAttempts: no live job was claimed or credential issued.

## Tests and checks

Commands executed with `.venv` Python:

```powershell
.\.venv\Scripts\python.exe manage.py test automation_api.test_worker_api --noinput --verbosity 1
.\.venv\Scripts\python.exe manage.py test automation_api.test_worker_bridge --noinput --verbosity 1
.\.venv\Scripts\python.exe manage.py test --noinput --verbosity 1
.\.venv\Scripts\python.exe manage.py migrate --noinput
.\.venv\Scripts\python.exe manage.py showmigrations workorders automation_api audit accounts
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m pip check
```

- API-focused run: 25 tests passed; an additional XML-reservation test was added
  before the final suite.
- Windows bridge test: passed a real HTTP Health/Poll/repeated Poll/Start/recovery
  guard/PDF upload/result/Publish retry/empty queue round trip. It used an isolated
  test server, temporary config/VM paths, fake two-page PDF and fake XML.
- First combined suite exposed transactional-test fixture isolation (a test flush
  removed seeded definitions). Fixed explicit fixtures for those test classes.
- Final full suite: **124 tests passed in 30.960 seconds**. Includes concurrent
  claims, auth/revocation, leases, immutable input mapping, expiry, operator recovery,
  ownership, malformed/oversized/hash-mismatched files, rollback/file cleanup,
  idempotence, exact result paths, protected downloads, and all prior regressions.
- Expected injected failures produced sanitized API log lines; Windows test
  connections also produced test-server broken-pipe warnings without failed checks.
- PowerShell parser check passed. The helper also ran through the real PowerShell
  executable in the bridge test; it was not merely syntax-checked.
- Six migrations applied successfully. No pending model changes, zero system-check
  issues, and no broken Python requirements.
- Live loopback unauthenticated health/current endpoints return 401 and no-store;
  public media returns 404. Listener remains 127.0.0.1:8001.

The human-readable audit labels were clarified after the full suite; migration
consistency was checked again. No behavioral implementation changed afterward.

## Remaining work and limits

Configure a concrete private HTTPS path from the Hyper-V VM to the dashboard,
provision/transfer the worker credential, create the PAD wrapper using the setup
guide, and run an attended fake-data test of the actual existing Tax-Filing flow.
That test must verify inputs are not overwritten by internal defaults and that
the flow honors its per-attempt OutputFolder. Neither was asserted from code tests.

The helper does not launch PAD, keep an RDP desktop alive, or provide unattended
execution. Long-running Stage 1 needs a reviewed lease/renewal design. Upload and
database storage are not a distributed filesystem transaction: handled failures
clean up their newly written file, but a process crash can leave a private orphan
for later cleanup. No success status is recorded before the artifact checks.

PDF validation is structural, not malware scanning or proof of matching tax data.
XML existence is checked by the helper inside the VM; Django validates reported
identity/path and never opens the VM drive. Approval/PDF hash binding, Stage 2,
actual BIR submission, and production deployment remain outside this delivery.

Git stays on `master` with no commits; project files are untracked as before.
Nothing was staged, committed or pushed. `.env`, databases, media, backups, secrets
and worker journals remain ignored. Existing user credentials were unchanged.
