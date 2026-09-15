# Deployment components and boundaries

These are the deployment boundaries. The Stage 1 API is implemented locally;
Hyper-V connectivity and the PAD wrapper still need setup. No LAN deployment is active.

| Component | Responsibility and location |
| --- | --- |
| Dashboard host | Host computer or another internal office machine running Django and the SQLite prototype. Manages work orders, approvals, audit history, and protected review files. Milestone 1 binds only to loopback; startup verified on `127.0.0.1:8001` after the user approved an available port because 8000 was occupied. The existing user-started development server currently uses that loopback endpoint. |
| Automation VM | Dedicated Windows VM accessed through Remote Desktop. Runs PAD and eBIRForms, generates files, and executes both existing desktop stages. Django does not launch PAD. |
| Internal API connection | Future authenticated HTTP connection initiated by the PAD polling worker to Django. Transfers work, approval metadata, results, and merged PDF uploads. Network address, TLS, firewall, and VM connectivity are deferred. |
| Protected dashboard file storage | Dashboard-local `media/`, separate from public static assets. Receives a protected copy of each uploaded review PDF; Django computes/verifies SHA-256. Future views authorize every read/download. No public media route exists. |
| VM-local eBIRForms XML storage | `C:\eBIRForms\savefile` inside the VM. XML normally stays here so Stage 2 can reopen the exact saved return through eBIRForms. Django retains expected filename, VM-local path, and work-order association as metadata. |

## VM-local paths

- `C:\eBIRForms\savefile`: saved XML returns.
- `C:\eBIRForms\profile`: eBIRForms profile storage.
- `C:\TaxAutomation\Working`: generated page PDFs and merged review PDFs.

All three paths belong to the automation VM. They are not dashboard-host paths,
shared drives, browser-accessible URLs, or files that Django may directly open.
An identically named path on the dashboard computer would be a different location.

## Intended preparation and review sequence

1. Django queues a work order; PAD polls and leases it through the future API.
2. Existing Stage 1 runs inside the VM, saves XML, and generates the merged PDF.
3. PAD uploads the merged PDF and reports the saved XML result to Django.
4. Django stores its own protected PDF copy and computes/verifies SHA-256.
5. A work order may enter `AWAITING_SUBMISSION_APPROVAL` only after both the
   prepared PDF and saved XML result have been recorded successfully. The final
   transaction and upload/result ordering design belongs to Milestone 5.
6. An authorized human reviews the protected PDF; approval is tied to its exact
   SHA-256 and prepared work-order version. Critical changes invalidate approval.
7. PAD polls for approved Stage 2 work and runs it in the same VM. It must reopen
   the exact expected saved return, never the first or newest return.
8. Stage 2 stops at `APPROVED_READY_TO_SUBMIT`. Actual BIR submission is outside
   this web application and remains disabled in PAD during fake-data testing.

A VM-local XML path is a worker-reported record, not proof established by Django
opening that path. Stage 2 must perform the relevant file/return checks inside
the VM. The PDF hash binds review approval to the dashboard's protected PDF copy;
it does not independently prove the XML contents match that PDF.

The VM needs an available desktop session for the existing UI automation. RDP
resolution/scaling and application sizing affect OCR/image-based steps. This
milestone does not modify the VM, desktop flows, or networking.

## Deferred decisions

- Implemented in Milestone 2: TIN segments 3/3/3/5 ASCII digits, three-character
  uppercase alphanumeric RDO, and explicit ATC from the VM-verified 2551Qv2018
  list. Friendly RDO/ATC input is normalized; identifiers retain leading zeros.
- Initial filing support: calendar-year `2551Qv2018`, `YearEndMonth = "12"`;
  later fiscal support must be accommodated in the future design.
- Milestone 5: lease duration, priority, retries, API transaction ordering, worker
  authentication, and same-VM association for Stage 2.
- Integration planning: heartbeat, worker pause/maintenance, dashboard LAN address,
  VM connectivity, and deployment security. No network changes are authorized now.

## Client-centered data architecture

`Client` ? `ClientFilingProfile` ? `FormDefinition`; each `WorkOrder` belongs to
one client and profile. The unique client/form association determines which
filings the later client-centered dashboard will display. Individual and
non-individual client types are explicitly entered. Existing legacy work orders
are not automatically matched to clients or assigned a client type.

A work order has immutable numbered `WorkOrderSnapshot` revisions containing its
client, form, profile, period, and form data. The current revision is materialized
in read-only historical columns for the existing displays. Editing source
configuration does not rewrite these snapshots. Preparing requires active
configuration, matching source versions and values, a registered automation key,
valid form data, and explicit zero-filing confirmation. Refreshing a snapshot
returns the order to draft and clears confirmation. Snapshot SHA-256 verifies
snapshot serialization; it is separate from the future uploaded PDF hash and is
not a digital signature or proof against a database administrator.

The explicit definition registry currently implements only `2551qv2018_zero`,
which routes to `PREPARE_2551QV2018_ZERO`. `planned_1701q` has no confirmed version,
automation key, or preparation availability. Unknown definitions fail closed for
preparation. Future definitions must add their own validators and tested routing;
there is no fallback to the 2551Q flow. Submission availability remains disabled.

See [the implementation report](client-architecture-report.md) for migration and
service details. No API, PAD leasing, client-list navigation, or submission was
added during this architecture revision.


## Stage 1 API now implemented locally

The [worker setup guide](worker-api-setup.md) and [implementation report](worker-api-report.md)
supersede earlier deferred API notes above for Stage 1. Authenticated claims,
immutable attempt/snapshot association, one execution slot, 30-minute leases,
explicit renewal/recovery, protected PDF upload and exact VM XML result reporting
are implemented. The Windows bridge is tested over local HTTP against an isolated
Django test server. It never launches PAD itself. PDF download is permission-gated.
Success enters Awaiting submission approval only after PDF/hash and XML metadata
are recorded. Stage 2/approval/submission remain absent, and private networking
has not been changed. The execution VM and dashboard host remain distinct.
