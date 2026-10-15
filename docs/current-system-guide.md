# Current system guide

Reviewed 15 October 2026 (Asia/Singapore). Application reporting uses Asia/Manila.
This guide records the implemented source and observed deployment behavior. It is
not a determination of a taxpayer's filing obligations or ATC eligibility.

## 1. Components and ownership

- Django serves client configuration, worksheets, work orders, approval, PDFs and reporting.
- SQLite stores versioned configuration, immutable filing snapshots, draft revisions and audit events.
- A Windows VM runs one `eBIR_Work_Order_Agent` parent PAD flow and form-specific child flows.
- `WorkerBridge.ps1` claims preparation, writes attempt inputs, verifies output and publishes the PDF.
- `Stage2Bridge.ps1` handles separately approved revalidation/submission, success evidence and result reporting.
- eBIRForms creates the actual return XML and printable PDF. Django never treats a worksheet as a submitted return.
- Receipt and archive services retain evidence and copy packages to configured client folders.

The current deployment uses HTTPS on port 8443. Environment files, worker credentials,
lease tokens, journals, databases, client documents and actual return artifacts are
operational data, not source control content.

## 2. Supported forms

| Form | Preparation implemented | Important limits |
| --- | --- | --- |
| 0619E | Zero and supplier withholding | Original private-agent; first two months of each calendar quarter; nonzero route excludes credits and penalties |
| 0619F | Zero | Existing original private-agent zero contract |
| 1600VT | Zero | Existing zero contract; no nonzero worksheet |
| 1601C | Zero and payroll totals | Original private-employer; payroll scope excludes adjustments, credits, relief and penalties |
| 1601EQ | Zero and quarterly supplier withholding | Original calendar-year private-agent; up to six ATC groups; no over-remittance disposition, amendments or prior-quarter carryover |
| 2550Q | Zero | Calendar-year original full-quarter; Micro, Small, Medium and Large classifications; no nonzero VAT schedule |
| 2551Q | Zero | Existing calendar-year zero route and validated ATC contract |
| 1604E, 1701, 1701A, 1701Q | Catalog only | No enabled PAD preparation |

Preparation availability is not submission authorization. Submission switches default
off in source; install and validate the associated PAD flow before enabling a form.
Nonzero worksheet jobs require prepared-PDF approval, rather than advance approval.
QAP generation/export is not connected to the quarterly worksheet.

## 3. Client filing cards and overview

Cards are assigned through client filing profiles and reviewed registration setup.
0619E was checked for all 83 companies with reviewed 0619E registration and all three
configured test companies (86 clients total). Missing cards were added to Test Company 2
and the dummy automation test client using audited catalog services. Companies without
0619E registration were not generally assigned that card. This was a deployment data
update, not a migration that automatically gives every future client 0619E.

The Overview `By form` breakdown now includes all seven supported preparation forms,
even with zero filings in the selected range. The form dropdown uses the same allowlist.
Archived filings are excluded. Counts describe work orders in the selected creation-date
range; they are not counts of registered clients or a list of all BIR forms.

## 4. 0619E monthly worksheet

1. Open a client's 0619E filing card and select zero filing or supplier withholding.
2. For withholding, choose a completed eligible month; quarter-ending months use the quarterly workflow.
3. Enter rows manually, paste Excel cells, or download/fill/upload the Excel template.
4. Preview calculated amounts and explicitly save the reviewed draft.
5. Open `Review and prepare 0619E`, review the saved revision and queue preparation.
6. Review the resulting PDF before any submission approval.

The manual editor supports 100 transactions. Workbook import supports up to 500 rows,
5 MB compressed and 30 MB expanded. Import uses a selected monthly sheet; optional
period data must match the chosen month. Recalculate and save Excel before importing
because formula results may be cached. Prior draft revisions remain available.

### Excel clipboard paste

Both 0619E and 1601EQ support:

- One column pasted into its corresponding first input (payee, TIN, ATC, base or reference).
- Five columns: payee, TIN, ATC, tax base, reference.
- Seven columns: registered name, TIN, ATC, tax base, rate, withholding, particulars.
  Paste this range into Supplier / payee. Excel rate and withholding columns are ignored;
  the app derives rates from its ATC catalog and calculates withholding.

Exclude headers and Total rows. Paste starts at the selected row and can replace entries
below it; extra rows are added automatically. Review before saving. Text is parsed as TSV,
including quoted cells; malformed ranges and excessive lengths are rejected before changes.
0619E retains its 100-row manual-editor limit; use workbook import for larger batches.
1601EQ supports 500 rows. New quarterly pasted rows inherit the starting row's month.
The ordinary quarterly Add transaction button advances to the next month, capped at the
quarter's final month. The month remains editable.

## 5. 1601EQ quarterly worksheet

Select year and quarter, then enter the three months' supplier transactions. `Load from
0619E drafts` loads the first two months and replaces unsaved rows. Add the third month's
transactions manually or by paste. ATC rates are read-only catalog values.

First- and second-month remittance inputs prefill from saved 0619E withholding totals;
they remain editable and saved overrides are retained. Missing monthly drafts default
to zero. These defaults are convenience values, not evidence of actual payment.
Submission of a monthly return alone is not a payment record.

Surcharge, interest and compromise are entered amounts; the worksheet does not calculate
penalty rates. Total penalties is calculated from these three fields.

Save a reviewed draft, then choose `Review saved draft for PAD`. The preparation review
shows ATC totals, remittances, individual penalties, rounding adjustments and amount due.
`Queue PAD preparation` opens a modal with client, quarter, revision and amount. `Back to
review` or Escape closes it without queueing; `Confirm & queue preparation` posts explicit
review confirmation. The CSRF token, signed preview, actor, profile/source versions and
draft version are validated. A repeated request is idempotent. Later worksheet edits do
not alter an existing work order's snapshot.

### Rounding compatibility

The worksheet keeps transaction-level rounded withholding. PAD preparation consolidates
the base for each ATC and mirrors the installed eBIRForms 7.9.6.1 calculation:

```text
value = binary64(base) * binary64(rate) / 100
cents = floor(value * 100 + 0.50000000001)
```

This is intentionally the application's arithmetic, not generic decimal half-up rounding.
For WC850, base 7,751,429.00 at 0.5% produces 38,757.14 in the installed application.
The four example transaction taxes sum to 38,757.16, so the preparation adjustment is
-0.02. The intermediate decimal-only implementation expected 38,757.15 and was superseded.

The review displays per-ATC and net adjustments without editing transaction bases,
remittances or penalties. The XML guard still requires exact agreement with the prepared
return; no general one-cent tolerance or validation bypass was introduced. A future
eBIRForms version must be checked before assuming identical rounding behavior.

## 6. Worker input and validation contracts

| Capability | Attempt input | XML verifier |
| --- | --- | --- |
| PREPARE_0619E_SUPPLIERS | SupplierSchedule, WithholdingTotal; suppliers.json | Test-0619EPreparedXml.ps1 |
| PREPARE_1601CV2018_PAYROLL | Reviewed payroll totals; payroll.json | Test-1601CPayrollXml.ps1 |
| PREPARE_1601EQ_SUPPLIERS | QuarterlySchedule, QuarterlyTotals; quarterly.json | Test-1601EQPreparedXml.ps1 |

The input files live inside the attempt's OutputFolder. Missing optional schedule files
select the existing zero path. Never insert nonzero values while falsely marking a job zero.
Migrations 0025-0030 add the worksheets, 0619E definition and confirmation constraints.

The quarterly bridge maps ATCs through `1601eq-atc-controls.json`, sorts by installed picker
index and passes grouped bases and payments. The PAD child selects withholding Yes,
opens ATCs, tabs through the picker and selects the specified indices, then fills bases,
remittances and penalties, validates, saves and prints. The mapping is tied to the installed
private-agent ATC picker. More than six groups and negative tax due are rejected.

Verifiers check identity, period, scope, each amount and unused fields. Quarterly verification
checks exact ATC membership, no duplicates, bases, rates, withholding, credits, penalties and
total due. Stage 2 repeats relevant checks against the approved snapshot before proceeding.
Existing XML is never silently overwritten. Worksheet and nonzero preparation review tokens expire after 30 minutes.

## 7. Recovery and cancellation

Always identify the exact work order, attempt, stopped action, journal phase and artifacts.
Do not print worker credentials or whole journals to logs.

| Observation | Correct recovery |
| --- | --- |
| No output; PAD stopped during input | Confirm both flows stopped, use guarded abandon/retry services, then let Poll retire the matching released journal |
| PDF/XML exist; journal Publishing | Inspect and verify output, then retry Publish only; do not repeat desktop preparation |
| XML differs from expected amounts | Stop, diagnose source/input/arithmetic mismatch; never fake success or loosen checks blindly |
| Submission success already visible; reporting failed | Preserve screenshot/journal and replay Stage2 Publish only; never submit again |
| ArchivePending | Retry archive only |
| Existing XML or reserved filename | Resolve the existing filing and its evidence; do not delete XML to bypass the guard |

Observed repairs include 1601C initial TIN population, dynamic saved-return selectors for
1601C/1601EQ, JSON-shaped Stage 2 reporting failures, and quarterly ATC keyboard navigation.
See the linked incident guides for their dated evidence. Parent `Failed to run flow` is a
wrapper error: inspect the child and bridge result before choosing recovery.

The quarterly rounding incident was recovered without rerunning PAD: the unchanged
immutable schedule was checked, the journal backed up, only derived totals refreshed from
the corrected server calculation, the existing XML verified exactly, and Publish retried.
This is a controlled repair procedure, not permission to edit journal business inputs.

`Cancel filing` is for eligible unapproved filings awaiting approval. It marks CANCELLED,
archives the row, blocks submission, retains documents/audit history and queues XML cleanup.
The worker moves the matching XML into its Cancelled archive when safe and idle. Ordinary
archival hides a record but is distinct from cancellation. Active runs or approved/submitted
filings must go through their guarded recovery workflow. Recent test cleanups were audited
cancellations, not hard deletes; they do not delete saved monthly/quarterly drafts.

## 8. Deployment and rollback

1. Review Git diff, back up source, database, deployed image and affected PAD flows.
2. Install requirements (including openpyxl), run `manage.py check`, migrations and relevant tests.
3. Deploy Django code/templates; run `collectstatic --noinput` for changed static assets; restart/reload web workers.
4. When installing worker changes, stop PAD only after resolving any active task. Install bridge and verifier files together.
5. Import the correct PAD parent/child exports, preserving inputs/outputs and selectors. Update capabilities only after installation.
6. Preserve worker.json credentials, journals and existing return files. Run one parent worker.
7. Test synthetic preparation through PDF review and exact XML validation. Submission is a separate authorization step.

The running Linux deployment uses source under `/home/nodeadmin/ebir-deployment/tax-automation`
and container `ebir-server-web-1`, with application `/app` and persisted `/data`. Update both
source and runtime to avoid drift. Container copies require the appropriate container user;
non-root extraction can leave partial updates. Verify completion and reload before declaring
deployment successful. For rollback, restore the known matching source/image; assess migrations
and active jobs before any database rollback. Never restore an old database over newer filings.

A Git push does not itself deploy or replace flows saved in PAD. Raw local PAD exports may
embed captured screenshots and client values; keep them in restricted backup storage. The
versioned inventory records their locations and hashes without publishing their contents.

## 9. Verification evidence and limits

- 0619E assignment: 86 client card/preparation pages checked; no work orders created by those checks.
- Excel paste: live 7-column and single-column paste, automatic row addition, catalog rates and preview total checked; test edits not saved.
- Quarterly integration: Test Company Q3 preparation completed through PAD, verified XML and one-page PDF; no BIR submission.
- Quarterly rounding recovery: Test Company 2 Q2 existing PDF and XML matched 48,757.14 due; attempt successfully published without desktop rerun.
- Modal: open/cancel verified without queueing. Layout: rendered review inspected after deployment.
- Form overview: zero-count 0619E and filtering tested locally and against deployed endpoint.
- Focused suites passed at their respective changes: 43 quarterly/1601EQ tests, 12 worksheet tests, 14 0619E integration tests and 6 overview tests.

Those counts are dated checks, not a claim that every live form or BIR submission path was
exercised. See the [release validation note](release-2026-10-15.md) for the full-suite result at this Git update.
Cancelled test work orders no longer appear in active history. The saved artifacts remain
historical evidence and should not be submitted as real returns.

## 10. Code map

- `workorders/withholding_views.py`, `expanded_withholding.py`: 0619E drafts/import.
- `supplier_0619e.py`, `supplier_views.py`: immutable monthly preparation.
- `payroll_1601c.py`, `payroll_views.py`: payroll totals/review.
- `quarterly_withholding.py`, `quarterly_views.py`: quarterly draft calculations/UI.
- `quarterly_1601eq.py`, `quarterly_prepare.py`: PAD totals, rounding and signed queue.
- `static/quarterly-excel-paste.js`: TSV parser shared by monthly/quarterly paste.
- `static/supplier-excel-paste.js`, `quarterly-worksheet.js`: editor behavior.
- `automation_api/worker_services.py`, `stage2.py`: worker payloads and lifecycle.
- `worker/WorkerBridge.ps1`, `Stage2Bridge.ps1`, `Test-*Xml.ps1`: VM contracts and verification.
- `workorders/dashboard_actions.py`: guarded cancel/archive.
- `workorders/views.py`, `templates/workorders/overview.html`: overview/filter allowlist.
