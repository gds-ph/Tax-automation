# Prepared PDFs in client folders

Updated 6 October 2026.

After Stage 1 successfully reports **Awaiting submission approval**, the server queues a copy of the verified Prepared return PDF into the client's office folder. It does not wait for approval, submission, or a BIR receipt. No PAD or VM installation is required for this copy.

## Destination and filename

The copy uses the same client mapping and destination resolver as the final package: prefer `BIR`, then `BIR FILING`, then `FILED RETURNS` under the mapped company folder. Monthly filings use `<root>/<filing year>/<MM MONTH>/`; quarterly filings stay directly under the selected root. Missing archive roots are reported for correction rather than guessed.

The copy is named `<original stem without _COMPLETE>_PREPARED_<work-order UUID>.pdf`. The work-order identifier distinguishes separate filings for the same period. The final package keeps its existing filename. Neither the protected dashboard PDF nor the VM PDF is moved or renamed.

## Processing and status

The existing receipts background process also checks queued PDF copies each cycle (normally every minute, plus processing time). A temporary service failure or missing client mapping retries after five minutes. Preparation and submission do not wait for this operation.

In **Documents → Prepared return**, the dashboard shows the saved relative path, queued copy, scheduled retry, or need for operator review. The server verifies the source hash and the uploaded copy. If a previous upload succeeded but its acknowledgement was lost, it recognizes the matching existing file. A different file at the destination or a changed source blocks copying for review; it is not overwritten.

Cancelled filings retain their prepared PDFs, including any client-folder copy. The separate cancellation worker moves only the VM XML as described in the [cancellation guide](cancelled-xml-cleanup.md).

## Existing filings and operations

New successful preparations are queued automatically. Existing filings are not silently backfilled. Administrators can explicitly queue all existing, unarchived, successfully prepared returns with:

```text
python manage.py archive_prepared_returns --include-existing
```

Without that option, the command only processes pending copies. Each run handles up to 20 due jobs; the background process continues the remainder. An existing filing can also be queued using `automation_api.prepared_archive.enqueue(order)` after checking its client mapping and preparation result. Keep the receipts background service running even when there are no submitted filings.
