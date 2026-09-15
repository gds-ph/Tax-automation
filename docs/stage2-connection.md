# Stage 2 connection: reopening and validation

This integration runs the Stage 2 flow described in the handoff document. It does NOT enable Submit / Final Copy or send a return to BIR. Dashboard approval is stored separately as approval for this rehearsal, bound to the current snapshot and PDF hash. The existing actual-submission flag stays false.

## VM setup

1. Stop the agent flow and close eBIRForms between jobs. Copy worker/Stage2Bridge.ps1 into C:\TaxAutomation\Stage2Bridge.ps1. Keep worker.json and all journals unchanged.
2. Give the Stage 2 desktop flow an unambiguous name (for example eBIR_Stage2_Revalidate). Keep its Submit / Final Copy action disabled. Remove temporary blocking message dialogs for unattended execution. Its output variable must be SubmissionStatus.
3. In the existing agent wrapper, inside If Job['HasTask'] = False, BEFORE Wait 15 / Next loop, add the Stage 2 block below. This lets Stage 1 and Stage 2 share one PAD agent. Do not run a second independent agent concurrently.

## Stage 2 block

Run PowerShell script, output Stage2Response:

```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\TaxAutomation\Stage2Bridge.ps1'))) -Action Poll
```

Convert Stage2Response from JSON into Stage2Job.
If Stage2Job['RecoveryRequired'] = True: Stop flow (operator review).
If Stage2Job['HasTask'] = True:
- Run the same script with -Action Start, output Stage2StartResponse; convert JSON to Stage2Start.
- If Stage2Start['Started'] is not True: Stop flow.
- Run desktop flow eBIR_Stage2_Revalidate; Wait for completion ON.
- Map each input below to %Stage2Job['Inputs']['INPUT_NAME']% (Boolean remains Boolean):
  TIN1, TIN2, TIN3, TIN4, RDOCode, FormSelectionText, ExpectedFormNumber, FilingYear, FilingQuarter, YearEndMonth, ApprovedForSubmission, WorkOrderId, ApprovalId, ApprovedBy.
- Additional payload fields ApprovedPdfSha256 and SubmissionEnabled are available. Stage2Bridge verifies the local PDF against the approved hash before Start. SubmissionEnabled must remain False. ApprovedForSubmission=True only opens the documented rehearsal gate; it never authorizes enabling the Submit action.
- The child must derive the expected filename and check it exactly as described in the handoff, rather than retaining prototype constants. Replace work-order verification constants with the supplied identifiers and derived return identity.
- Store its output SubmissionStatus in Stage2SubmissionStatus.
- Set Stage2Result to a custom object with AttemptId: Stage2Job['AttemptId'], SubmissionStatus: Stage2SubmissionStatus. Convert it to JSON as Stage2ResultJson.
- Write Stage2ResultJson to %LocalAppDataPath%\TaxAutomationWorker\stage2-result.json, overwriting. Retrieve LOCALAPPDATA first if LocalAppDataPath is not yet set.
- Run Stage2Bridge.ps1 with -Action Publish. Convert response; inspect Status.
End the HasTask condition, then retain Wait 15 seconds and Next loop.

Accepted results: APPROVED_READY_TO_SUBMIT, BLOCKED_NOT_APPROVED, WORK_ORDER_VERIFICATION_FAILED, SAVED_RETURN_NOT_UNIQUE, SAVED_RETURN_ROW_NOT_FOUND, FAILED_SYSTEM. SUBMITTED is rejected.

## Dashboard

Approver and Administrator roles may use Approve & run Stage 2 on a prepared work order. Approval is idempotent. Only the same agent that completed preparation may claim it, because the files live on that VM. The global attempt slot prevents simultaneous preparation and Stage 2. Expired attempts and interrupted desktop runs require operator recovery; never delete a journal to retry them.

The work-order page displays Stage 2 state. Refresh after the VM reports its result. The prepared work order remains awaiting submission approval because no live submission is performed.

## Testing

Use the dummy client. Expected final state is APPROVED_READY_TO_SUBMIT, with Submit / Final Copy disabled throughout. Backend and Windows bridge tests use isolated fake data; the actual VM/PAD selector mappings still require this manual setup and an end-to-end test.
