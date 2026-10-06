# Reset a stuck preparation worker

Reviewed 2 October 2026. Release and worker-update download require operator permissions; Retry preparation requires work-order change permission. See [the documentation index](README.md).

## Dashboard recovery (recommended)

Install the dashboard recovery bridge once on the VM: on an interrupted filing's
Overview tab, expand **One-time worker update**, download the ZIP, extract it, and
double-click `Install-DashboardRecovery.cmd` with both PAD flows stopped. This
updates only `C:\TaxAutomation\WorkerBridge.ps1`; credentials and journals stay intact.

For subsequent interrupted Stage 1 runs:

1. Stop the parent and child PAD flows and close leftover eBIRForms windows.
2. Open the matching filing in the dashboard. An operator with worker-management
   permission confirms the flows stopped and chooses **Release interrupted run**.
3. Start one parent worker. Its next poll verifies the exact attempt, worker,
   lease token, work-order ID and preparation automation key with the server.
   Only an operator-released (`ABANDONED`) attempt allows the bridge to back up
   its `Running` journal and mark it completed. It does not start a filing in this poll.
4. Resolve the original failure, then choose **Retry preparation** on that filing.

No pasted PowerShell commands are needed after the one-time update. The dashboard
cannot stop PAD or modify an offline VM itself; the parent must run to perform the
local cleanup. An active or merely expired attempt is never cleared automatically.
`Publishing` journals and Stage 2 journals are not cleared by this recovery path.
If a network or identity check fails, the pending journal is preserved.

## Manual fallback for older workers

Use this when a **Stage 1 preparation** run stopped, the dashboard task has been released as **System failure**, and the worker still reports an earlier task or recovery required.

The dashboard and Windows VM keep separate records. Marking the task failed on the dashboard does not clear the VM's local journal. This procedure backs up and clears only that failed preparation claim; it does not fix the PAD action that originally failed.

## 1. Stop the desktop flows

On the automation VM:

1. Stop `eBIR_Work_Order_Agent`.
2. Stop any running child flow, including `Stage1_Prepare_1601EQ`.
3. Close leftover eBIRForms windows after stopping the flows.

Keep the flows stopped until the reset finishes. Run the commands below in **PowerShell on the automation VM, signed in as the same Windows user that runs PAD** (normally `Tax-Automation`). Do not run them on your development PC.

## 2. Identify the blocked preparation task

Paste this read-only command:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $journalPath = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\journal.json'
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    $journal | Select-Object Phase
    $journal.Claim | Select-Object AttemptId, WorkOrderId, AutomationKey
}
```

Copy the displayed **AttemptId** and **WorkOrderId**. Use the IDs from this run, never IDs from an earlier example.

This reset is for `Phase: Running` with an automation key starting with `PREPARE_`.

| What you see | What to do |
| --- | --- |
| `Running` and `PREPARE_...` | Continue below after releasing this exact task on the dashboard. |
| `Completed` | This preparation journal is already reset. Do not reset it again. |
| `Publishing` | A result is being reported or awaits reporting. Resolve reporting first; do not discard it using this guide. |
| `Requesting` or `ReadyToRun` | This is a different claim state. Do not use this reset. |
| Missing file, blank IDs, or another phase | Stop and inspect the actual error; do not create an empty journal. |

## 3. Release the matching dashboard task

Open the work order matching the **WorkOrderId** from step 2.

- If it still has an interrupted active run, use **Release interrupted run**, confirming that PAD and the desktop filing flow are stopped.
- If you already released that run and the order shows **System failure**, continue.
- If the order is awaiting approval, approved, submitted, or still actively processing, do not clear its journal with this procedure.

Confirm you are looking at the same work order and interrupted attempt. A failure on a different order does not authorize clearing this claim.

## 4. Back up and reset the local preparation journal

Paste the whole block into PowerShell. It asks for the IDs you copied and checks them again before writing. Type `RESET` only after step 3 is complete and both flows are stopped.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $expectedAttemptId = (Read-Host 'Paste the failed preparation AttemptId').Trim()
    $expectedWorkOrderId = (Read-Host 'Paste its WorkOrderId').Trim()
    if ([string]::IsNullOrWhiteSpace($expectedAttemptId) -or
        [string]::IsNullOrWhiteSpace($expectedWorkOrderId)) {
        throw 'Both IDs are required. Nothing changed.'
    }

    $confirmation = Read-Host 'Both PAD flows are stopped and this exact run is released as System failure. Type RESET'
    if ($confirmation -cne 'RESET') {
        throw 'Reset cancelled. Nothing changed.'
    }

    $journalPath = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\journal.json'
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    if ($journal.Phase -ne 'Running' -or
        $journal.Claim.AttemptId -ne $expectedAttemptId -or
        $journal.Claim.WorkOrderId -ne $expectedWorkOrderId -or
        $journal.Claim.AutomationKey -notlike 'PREPARE_*') {
        throw 'Journal state or task does not match. Nothing changed. Repeat the read-only check.'
    }

    $backupPath = "$journalPath.backup-$([guid]::NewGuid())"
    Copy-Item -LiteralPath $journalPath -Destination $backupPath -ErrorAction Stop
    $journal.Phase = 'Completed'
    $journal.Claim = $null
    $journal.Result = $null
    [IO.File]::WriteAllText(
        $journalPath,
        ($journal | ConvertTo-Json -Depth 20),
        [Text.UTF8Encoding]::new($false)
    )

    $check = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    if ($check.Phase -ne 'Completed' -or $null -ne $check.Claim -or $null -ne $check.Result) {
        throw "Journal verification failed. Keep PAD stopped. Backup: $backupPath"
    }
    Write-Output 'Preparation journal recovered.'
    Write-Output "Backup: $backupPath"
}
```

The script checks the local record; **it does not contact the dashboard to verify release**. That is why step 3 must be completed first.

Expected final message: `Preparation journal recovered.`

## 5. Restart

1. Fix the PAD action that caused the original failure before retrying preparation.
2. Start **one** instance of `eBIR_Work_Order_Agent`.
3. Open the failed filing and choose **Retry preparation** under **Overview → Next action**. Check the client/TIN, form and period first.

Retry queues the same work order with its reviewed snapshot. The worker creates a new attempt; the failed attempt and audit history are retained. Resetting the journal alone does not queue a retry or approve a submission.

Retry is available to users with work-order change permission for system, missing-PDF and missing-XML preparation failures after the previous attempt finishes or is released. Active runs, archived filings, successful preparation, recorded files and Stage 2 approvals require review instead. Changed client/form settings must be reviewed in a new filing. Duplicate clicks are rejected using the work-order version. Retry does not clear the Windows journal: complete recovery above first if the worker stopped with a pending run.

Optional connection check:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'C:\TaxAutomation\WorkerBridge.ps1' -Action Health
```

`status: ok` confirms bridge connectivity; it does not confirm that PAD is running or that preparation succeeded.

## If it still stops

- Read the new error and repeat the read-only check. Do not repeatedly clear the journal without identifying the blocked task.
- A missing UI element requires fixing the selector or the expected screen in the child flow; a journal reset will not repair it.
- `SAVED_RETURN_NOT_UNIQUE` in Stage 2 requires checking that the saved XML matches the exact approved TIN, form, year, and quarter.
- A temporary network error requires restoring connectivity and retrying with the existing journal.
- A Stage 2 recovery message or `ArchivePending` is a separate issue. **Do not delete or reset `stage2-journal.json` using this procedure.** Submission may already have happened. For `ArchivePending`, retry the archive operation only, never the submission.

Keep the backup files for troubleshooting. Do not restore an old journal over a newer active task.
