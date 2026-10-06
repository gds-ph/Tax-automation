# Request preparation from the dashboard

Reviewed 2 October 2026. The parent now routes preparation for 2551Q, 1601C, 1601EQ and 0619F and polls Stage 2 when no preparation task is available. The pseudocode below illustrates Stage 1 only; retain the integrated Stage 2 branch. See [Stage 2](stage2-connection.md) and [recovery](worker-preparation-recovery.md).

The dashboard's Clients -> client -> Prepare 2551Q -> Queue preparation already
creates a validated, immutable work order. Keep the resulting task page open;
it refreshes every 10 seconds while queued or processing and shows the protected
PDF download when preparation succeeds. GET refreshes do not create/claim work.

The worker API and transfer were successfully tested from the VM. The installed parent loop is maintained by the operator in PAD. The instructions below describe its polling structure; Codex does not remotely edit or start that desktop flow.

## Cancellation cleanup update (6 October 2026)

An administrator installs the [one-time VM cancellation update](cancelled-xml-cleanup.md). Subsequent cancellations queue automatic XML archiving during idle parent polls; no additional PAD action is required. Pending/running cleanup blocks new desktop claims until processed. Close eBIRForms form windows and keep the updated parent worker running.

## Update eBIR_Work_Order_Agent inside the VM

With the flow stopped, surround ALL existing actions with a Loop condition:
first operand %True%, operator Equal to, second operand %True%.
The loop's End must be after Publish and the final Wait below.

Inside the existing If Job['HasTask'] = False, replace ONLY its Stop flow with:
Wait 15 seconds, then Next loop. Keep the Stop flow in RecoveryRequired, the
unsupported AutomationKey check, and the failed Started check.

After Publish, convert PublishResponse from JSON into PublishResult. If
%PublishResult['Status']% is not equal to AWAITING_SUBMISSION_APPROVAL, Stop flow.
This conservatively stops on a reported failure rather than starting more jobs.
Then Wait 15 seconds before reaching the loop's End.
All PowerShell, JSON conversion, child-flow and file-write action errors must
stop the flow; do not set On error to continue. A missing Status also stops.
Do not rerun the child after a Publish error; inspect and recover the attempt.

```text
Loop condition True = True
    Poll -> convert to Job
    If RecoveryRequired = True: Stop flow
    If HasTask = False
        Wait 15 seconds
        Next loop
    End
    If unsupported AutomationKey: Stop flow
    Start -> convert to StartResult
    If Started <> True: Stop flow
    Run desktop flow Tax-Filing - Copy (latest preparation flow; wait enabled)
    Build PreparationResult -> ResultJson
    Get LOCALAPPDATA -> write result.json, UTF-8, overwrite
    Publish -> convert to PublishResult
    If Status <> AWAITING_SUBMISSION_APPROVAL: Stop flow
    Wait 15 seconds
End
```

Start the wrapper once in the VM's unlocked interactive session. Leave it waiting
and request a filing from the dashboard. No need to manually run the child flow
for each request. The dashboard does not launch PAD, and this is not unattended
cloud execution. Keep Submit / Final Copy disabled while testing fake data.

For the next test, choose a different reviewed fake-data period, e.g. 2026 Q3.
The successful 2026 Q2 return reserves its XML filename while awaiting review;
do not reset that successful task or overwrite its XML to test the loop.
Never run the one-off printer-recovery archive script for a successful attempt.

Microsoft references: [Loop condition and Next loop](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/loops).


## Operational KPI cards and archival

Work orders and My tasks show five clickable counters: awaiting approval, in progress,
needs attention, waiting for a BIR receipt, and packages completed this calendar month.
Counters follow the client and filing-period filters and the selected task scope.
Completed uses the package finalization date in the configured local timezone.
Archived orders and the configured demo client codes (DUMMY-CLIENT-001,
TEST-639848605-00000, TEST-639852610-00000) are excluded from counters and their drilldowns.
The unfiltered task list still includes active tests for troubleshooting.

Operators with both change_workorder and change_agent can expand Archive filing on
an order detail page and confirm removal from active lists. This is a CSRF-protected,
version-checked POST with an audit event. Active runs and any submission approval
block archival. History, documents, and worker-local XML files are preserved.
