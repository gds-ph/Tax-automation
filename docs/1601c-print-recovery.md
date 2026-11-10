# 1601C PDF-print recovery — 10 November 2026

## Failure and repair

Stage1_Prepare_1601C stopped at action 130, the simulated population of the
page-number field. The error said the UI element did not support simulation.
The observed desktop still had Save Print Output As open: the preceding physical
Save click had not completed, despite being logged as successful. Therefore the
error alone does not establish that the underlying page field lacks support.

Saved these targeted changes in the installed flow:

- Both PDF Save buttons use simulated clicks against the existing button selectors.
- Page 2 navigation uses normal text population with a single click.
- Each Save is followed by a bounded 20-second check for a nonempty page PDF.
  Failure returns PREPARATION_FAILED_PDF_NOT_FOUND rather than navigating behind
  an unresolved save dialog.

The flow changed from 162 to 176 actions. Input/output contracts and other actions
were preserved. Copied-back action text matched the candidate after newline
normalization. Both embedded wait scripts passed PowerShell syntax parsing.
The Designer displayed no errors and returned to Ready after saving.

## Recovery and evidence

Recovered the existing October 2026 zero-return attempt by saving the pending
first page, navigating to page 2 using keyboard input, and printing its remaining
content. No tax values were changed and no preparation or submission flow was run.
The existing merge order (page 2 followed by page 1) was preserved. Logical page 2
spans two physical pages; the complete PDF contains three physical pages, accepted
by the server's existing 1601C policy. Rendered and inspected all three pages;
verified form, company, period and zero amounts. Taxpayer-text validation passed.
The payroll-specific validator is inapplicable to this ZERO claim.

Publication initially returned HTTP 409 because the lease expired during repair.
After locking and checking the same RUNNING attempt, execution slot, snapshot,
PROCESSING_PREPARATION order, active company record and absence of Stage 2 approval,
restored that attempt's lease for publication and recorded LEASE_RENEWED in the audit.
Retried only Publish, using the ordinary XML/PDF checks and result endpoint.
It returned AWAITING_SUBMISSION_APPROVAL. The local journal completed. No duplicate
return was prepared and nothing was submitted to BIR.

## Verification limits and backups

The manual recovery verifies printing and keyboard navigation for the current
return. It does not certify a fresh unattended run of the revised PAD actions.
Observe the next normal preparation before treating the repair as fully verified.
The parent worker was left stopped after recovery.

Full local exports (contain UI screenshot metadata; excluded from Git):

- C:\TaxAutomation-work\Stage1_Prepare_1601C.before-20261110.txt
- C:\TaxAutomation-work\Stage1_Prepare_1601C.after-20261110.txt

The action-only snapshot at pad-actions/Stage1_Prepare_1601C.actions.txt is for
review; importing it requires the corresponding local UI repository.
Taxpayer PDFs, XML, journal tokens and embedded screenshots are not committed.

## Fresh unattended verification — 10 November 2026

Restarted one parent worker with PreparationOnly enabled after the user selected
preparation-only testing. A fresh October 2026 1601C zero preparation completed
without manual intervention: page-one save, page-two navigation and save, merge,
and publication all passed. The server marked attempt
3d108449-7fbd-4735-afb6-c86ac4609657 SUCCEEDED and the work order
AWAITING_SUBMISSION_APPROVAL. This supersedes the earlier fresh-run verification
limit above. It does not certify other forms or submission flows.

The parent remains running in preparation-only mode. Stage2Bridge Poll returns
HasTask=false before claiming new work when worker.json PreparationOnly is present
and not boolean false. Existing active/reporting/archive recovery checks run first;
existing approvals and journals are retained. This operational flag was enabled
only in the local worker configuration (credentials are not committed). To resume
submissions, obtain user authorization, stop the parent, set PreparationOnly to
boolean false, then restart one parent. Do not change the approved queue merely
to test preparation.

Validation: PowerShell parser checks passed for the live and repository bridge;
a live Poll returned the preparation-only message with no task. Successful fresh
preparation verified that the parent can continue preparation with Stage 2 paused.

## Follow-up filename truncation repair

The next 1601C payroll run stopped cleanly with PREPARATION_FAILED_PDF_NOT_FOUND.
The page-one PDF existed under the truncated name CLOUDPU.pdf; the exact-path guard
prevented publishing it. Changed only the two Save Print Output As filename actions
from normal keyboard population to SimulatePopulateTextField (direct value entry).
The flow retains 176 actions, both save buttons and both readiness guards.
Copied-back full export matched the candidate after newline normalization; Designer
saved and returned Ready with no errors. Backups are local under
C:\TaxAutomation-work\Stage1_Prepare_1601C.before-filename-20261110.txt and
Stage1_Prepare_1601C.after-filename-20261110.txt.

The failed payroll attempt was already recorded FAILED with its execution slot
released and local journal Completed. Preserved its journal and existing XML/PDF;
did not reset or replay that filing. Restarted the parent in preparation-only mode.
That payroll filing still requires separate print-output recovery before approval.

The next restart encountered the same CLOUDPUFF order requeued while its XML already
existed. Start refused before any child ran. Recorded FAILED_BUSINESS through the
normal preparation-result service for that exact attempt, verified its prior
ReadyToRun local identity, backed up and completed its journal, preserving the
existing return files. Restarted the parent for the remaining queue. Do not retry
this payroll filing until the existing return and print outputs are reconciled.
