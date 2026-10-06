# Submitted XML archiving

Reviewed 2 October 2026. This guide concerns VM XML files. Final PDF packages on the office share use the separate [receipt/package workflow](bir-receipts.md). Preparation dashboard recovery does not clear Stage 2 or ArchivePending journals.

For cancellation before approval, use the separate [cancelled XML cleanup guide](cancelled-xml-cleanup.md). Its installer download is administrator-only. Neither XML archive workflow waits for final PDF package creation.

The VM archive destination is `C:\TaxAutomation\Archive\Submitted\<WorkOrderId>\<original filename>.xml`.
After the successful VM pilot, Stage2Bridge Publish now archives successful live
submissions automatically, after the server accepts their screenshot and result.
The PAD parent must wait for the child to finish, including closing the return,
before Publish. No extra PAD action is needed. Only install these updates while
the parent is stopped. No old completed receipts are bulk-archived on installation.
PDFs and screenshots remain in their existing locations. The dashboard's submission
status does not change; BIR confirmation remains pending.

Deploy `worker/Stage2Bridge.ps1`, `worker/WorkerBridge.ps1`, and `worker/Archive-SubmittedReturn.ps1` to
`C:\TaxAutomation` on the VM. New successful Publish operations preserve a private
receipt under `%LOCALAPPDATA%\TaxAutomationWorker\submitted\<AttemptId>.json` before
polling can replace the active journal. These receipts contain a lease token: never
paste or upload their contents. A still-completed old journal can also be used;
an old journal already overwritten by polling cannot be reconstructed by this script.

The standalone helper remains preview-first for manual archive operations.
Stop the parent agent and close the return in eBIRForms. Preview:

```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\TaxAutomation\Archive-SubmittedReturn.ps1'))) -ReceiptPath "$env:LOCALAPPDATA\TaxAutomationWorker\submitted\<AttemptId>.json"
```

The preview checks the successful journal, approved source identity, API result and
screenshot evidence, and shows source, destination and SHA-256. It writes no archive
and removes nothing. The API result replay is idempotent and does not launch PAD.

After checking the preview, use the same command with `-Commit`. The script copies
the exact XML, verifies SHA-256, writes an archive manifest, rechecks the source,
and removes only that file. Different existing archive bytes, changed working files,
reparse paths, and unsuccessful receipts are refused. Partial copy failures preserve
the source and require review; do not delete receipts or resubmit to fix an archive.
Retries after removal verify the archive and return success without another submission.
The manifest records the archive location locally; dashboard archive-link support is
not implemented. A normal Publish returns Status plus Archived=True and ArchivePath.

The VM pilot verified that the row disappears after reopening eBIRForms.
Keep the original filenames and manifests for restoration and duplicate checks.

## Recovery

After server acceptance the durable journal enters ArchivePending before attempting
archive operations. A failure leaves the submission recorded and stops Publish.
Both bridges refuse new polling work while this journal is pending. Start cannot
run the child again. Preserve the journal and receipt. Resolve any missing helper,
locked file or destination conflict, then retry only:

```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\TaxAutomation\Stage2Bridge.ps1'))) -Action Archive
```

This verifies/retries archiving without launching PAD, submitting, or reuploading
screenshots. Publish also resumes archive-only when the journal is ArchivePending.
Only a verified archive permits the journal to become Completed. Repeated Publish
on Completed returns the recorded status without deleting a newly recreated XML.
If the network response was lost before ArchivePending was saved, retry Publish
with the existing journal; its result reporting is idempotent.

Integration coverage uses a temporary VM folder and isolated Django test server:
preview leaves source intact; conflicting destination is rejected; archive contents
match; repeated commit works; a recreated different XML is not removed. Bridge
tests also cover automatic success, pending recovery in both pollers, Start refusal,
archive-only retry, completed replay and rehearsal leaving XML untouched.
