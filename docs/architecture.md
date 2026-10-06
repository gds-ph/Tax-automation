# Current architecture and operating boundaries

Reviewed 2 October 2026. See the [documentation index](README.md) for operating guides and historical reports.

| Component | Responsibility |
| --- | --- |
| Linux dashboard | Django and SQLite in Docker Compose; clients, filing profiles, immutable work-order snapshots, permissions, approvals, audit events and protected files. HTTPS is served by Caddy at `https://192.168.8.200:8443`. |
| Windows automation VM | PAD parent and form-specific children operate eBIRForms in an available interactive desktop session. The server does not launch or stop PAD. |
| Worker bridges | Bearer-authenticated polling, attempt-specific inputs, uploads, result reporting and local journals. A global execution slot serializes desktop attempts. |
| Client-files service | Reads the mounted office CLIENT share for registration documents and writes final packages to the configured company archive. |
| Background services | `receipts` checks mail and finalizes packages; `cards` generates saved COR suggestions. Neither runs PAD. |

## Filing lifecycle

Clients ? Filing cards ? choose form and period ? confirm supported zero-filing scope ? queue preparation. The four preparation definitions are 2551Q, 1601C, 1601EQ and 0619F. Other cards may be visible without automation.

The worker claims an eligible immutable snapshot, journals its start, runs the matching child, uploads the PDF and reports exact XML/PDF paths. Successful preparation enters Awaiting submission approval. Approval is bound to the snapshot and PDF hash. The originating worker then reopens the exact approved return and reports submission evidence. Mail receipt confirmation is separate from desktop success and does not establish final BIR validation.

The server's monthly/1601EQ submission switches default off but were enabled on the current deployment when checked on 2 October 2026. Live availability also depends on installed PAD routes, worker capabilities and per-return approval. Never infer a successful submission from a feature flag.

## Records and permissions

A Client has ClientFilingProfiles tied to FormDefinitions. WorkOrders preserve numbered, immutable snapshots. Editing a client does not change prepared filings; stale queued snapshots fail readiness checks. Audited services check permissions and expected versions. Audit safeguards protect application operations, not against privileged direct database access.

All active signed-in users gain client view/edit permission. Additional work-order, approval, document and worker-management permissions remain distinct. Current Feishu provisioning grants preparation and approval capabilities; it is not a view-only login. See [login permissions](feishu-login.md).

## Storage

- VM XML: `C:\eBIRForms\savefile`.
- VM eBIRForms profiles: `C:\eBIRForms\profile`.
- VM preparation output: `C:\TaxAutomation\Working\<WorkOrderId>\<AttemptId>`.
- VM submitted XML: `C:\TaxAutomation\Archive\Submitted\<WorkOrderId>`.
- VM credentials and journals: `%LOCALAPPDATA%\TaxAutomationWorker` under the PAD Windows user. Do not share their contents.
- Server private files: media under the app-data volume, including `final_packages`. Downloads require application authorization.
- Office final PDF: `\\192.168.8.251\Starlight\Starlight offline\CLIENT\<Company>\BIR`, falling back to the existing `FILED RETURNS` folder. New monthly packages add `<filing year>\<MM MONTH>`; existing files are not moved.

Django never opens VM-local C: paths. PDF hashes verify stored bytes, not XML/PDF semantic equivalence. Original COR PDFs stay on the office share; reviewed provenance and extracted suggestions are stored separately.

## Failure recovery

Leases last 30 minutes; expiry never proves the desktop flow stopped. Preparation retry is explicit, version-checked and preserves failed attempts. Active, successful, archived and approved filings cannot use that retry path. An operator must release interrupted work after stopping both PAD flows. With the dashboard recovery bridge installed, the next parent poll backs up and clears only the matching abandoned preparation journal.

Publishing and Stage 2 uncertainty require separate reconciliation. An acknowledged submission with ArchivePending requires archive-only recovery, never resubmission. See [recovery](worker-preparation-recovery.md) and [XML archiving](submitted-xml-archive.md).

## Deployment limitations

Only supported zero-filing scenarios are implemented. SQLite concurrency, desktop-session availability, selector maintenance, backups and restoration remain operational concerns. Code/API tests do not prove installed PAD selectors work. Historical implementation reports are retained for traceability rather than as current deployment instructions.
