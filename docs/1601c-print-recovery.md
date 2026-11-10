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
