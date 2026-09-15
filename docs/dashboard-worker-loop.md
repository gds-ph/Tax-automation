# Request preparation from the dashboard

The dashboard's Clients -> client -> Prepare 2551Q -> Queue preparation already
creates a validated, immutable work order. Keep the resulting task page open;
it refreshes every 10 seconds while queued or processing and shows the protected
PDF download when preparation succeeds. GET refreshes do not create/claim work.

The worker API and transfer were successfully tested from the VM. The remaining
manual PAD change is to keep the existing wrapper polling instead of stopping
when there is no job. This change has NOT been applied inside the VM by Codex.

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
