# Cancellation and VM XML cleanup

Updated 7 October 2026 (Asia/Manila).

## Who can cancel

Only a filing with status **Awaiting submission approval**, with no submission
approval or active worker attempt, can be cancelled. All other statuses are
blocked. Users who can view and edit work orders may cancel eligible filings.
Users who can approve submissions and view prepared PDFs also retain cancellation
access. Cancellation does not grant submission approval or worker-management
permissions. The VM update download remains admin-only.

Cancellation marks the filing Cancelled, removes it from active work, preserves
its dashboard PDF and audit history, and queues XML cleanup for the worker that
successfully prepared its current snapshot. Older cancellations are not
processed automatically.

## One-time installation: administrator only

Only active administrator (Django superuser) accounts can see **Download VM
cancellation update** or access its download URL. Staff status or worker-management
permission alone does not grant access. The server rejects non-admin direct URL
requests with HTTP 403.

1. Stop both parent and child PAD flows on the automation VM.
2. Sign in to the dashboard as an administrator. Open a filing awaiting submission
   approval, choose **Actions > Cancel filing**, then click **Download VM
   cancellation update**. Downloading does not cancel the filing; do not confirm
   cancellation just to obtain the installer. The download is also available to
   administrators on a cancelled filing's detail page.
3. If downloaded on another computer, copy `CancellationCleanup-Update.zip` to
   the automation VM. Right-click it, select **Extract All**, and open the
   extracted folder.
4. Run **Install-CancellationCleanup.cmd** using the usual PAD Windows account.
   Confirm the installer reports success.
5. Close eBIRForms form windows and restart one **eBIR_Work_Order_Agent** parent
   flow. No parent PAD action changes are required.

The installer backs up `WorkerBridge.ps1` and installs
`Archive-CancelledReturn.ps1` in `C:\TaxAutomation`, preserving credentials and
pending journals. This is a one-time update, not a download to run for every
cancellation. It is separate from the per-attempt SubmissionRecovery ZIP.

## Normal cancellation

1. Open an eligible filing and choose **Actions > Cancel filing**.
2. Tick the confirmation and click **Cancel filing**.
3. The updated VM worker processes its cleanup queue automatically when idle.
4. Check the cancelled filing's **Next action** panel for cleanup status.

| Dashboard status | Meaning / action |
| --- | --- |
| XML cleanup pending / in progress | Keep the updated parent worker running on the original VM and close eBIRForms form windows. An offline VM processes it after returning. |
| XML moved to Cancelled archive | The worker verified the archived XML and reported completion. Its destination is shown on the page. |
| XML cleanup needs review | Inspect the reported conflict or worker files. Do not delete journals or retry the BIR submission. |
| No XML cleanup was queued | This is an older cancellation; its VM files remain in place and require separate review. |

Pending/running cleanup blocks new desktop claims; it never interrupts a running
PAD attempt. Active preparation/submission journals and open `mshta` form windows
prevent movement. Missing helpers require installing the update before cleanup
can proceed.

## What moves, and what stays

The worker moves only the exact saved XML:

- From: `C:\eBIRForms\savefile\<filename>.xml`
- To: `C:\TaxAutomation\Archive\Cancelled\<WorkOrderId>\<filename>.xml`

PDFs remain in their existing VM and dashboard locations. The archive includes a
cleanup manifest and SHA-256 hash. The worker checks the cancelled identity,
original preparation worker, competing active filings, source/destination
boundaries, links, timestamps and destination collisions. It does not overwrite
other files or delete directories.

A per-cleanup manifest supports replay after a lost acknowledgement. A replacement
XML appearing after archival is left alone. After fixing a transport failure,
restart the parent worker with journals intact. File-validation failures require
operator review; they are not blindly retried.

Refresh or reopen eBIRForms after successful cleanup to verify the saved return
has disappeared from its list. The production VM installation and this UI check
must be verified on the VM; server deployment alone does not establish either.

## Difference from submitted XML and final packages

The concept is similar to [submitted XML archiving](submitted-xml-archive.md), but
the triggers differ:

| Workflow | Trigger | Destination |
| --- | --- | --- |
| Cancelled XML | Eligible filing is cancelled; idle worker processes cleanup | `C:\TaxAutomation\Archive\Cancelled\<WorkOrderId>` |
| Submitted XML | Server accepts the successful submission screenshot and result | `C:\TaxAutomation\Archive\Submitted\<WorkOrderId>` |
| Final PDF package | Matching receipt email is processed | See the [receipt/package guide](bir-receipts.md) |

Submitted XML archiving occurs before final package creation; it does not wait
for the BIR receipt. Moving a local XML never withdraws a return sent to BIR.
