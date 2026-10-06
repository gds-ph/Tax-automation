# Stage 2: approved submission connection

Reviewed 2 October 2026. The detailed 2551Q mapping below is the original route example. Current routing also includes `SUBMIT_1601CV2018`, `SUBMIT_1601EQ` and `SUBMIT_0619F`; use each form integration guide for exact inputs and filenames. Installed selectors must be verified separately.

The dashboard now supports explicit submission approval. Earlier rehearsal approvals
remain rehearsal-only; they are never upgraded. No PAD flow is remotely edited or
started by deploying this code. Complete the VM/PAD mapping below before approving.
Do not approve the Q1 return already submitted manually: the API cannot discover
manual BIR submissions. Success means the app reported success, not verified BIR acceptance.

## 1. Deploy the bridge

Stop the wrapper between tasks. Copy `worker/Stage2Bridge.ps1` from this project to
`C:\TaxAutomation\Stage2Bridge.ps1` inside the VM. Preserve worker.json and both journals.
Use the same worker credentials as Stage 1. Do not run a separate competing agent.

## 2. Update Stage2_Open_Approved_Return

Keep the working selectors. Replace test constants with input variables.
Inputs already used: TIN1, TIN2, TIN3, TIN4, RDOCode, FormSelectionText,
ExpectedFormNumber, FilingYear, FilingQuarter, YearEndMonth, ApprovedForSubmission,
WorkOrderId, ApprovalId, ApprovedBy.

Add inputs:
- SubmissionEnabled (Boolean, default False)
- ApprovedReturnPeriod (Text)
- ApprovedSavedReturnName (Text)
- ApprovedXmlPath (Text)
- SuccessScreenshotPath (Text)

Keep outputs SubmissionStatus; add SuccessScreenshotPathOutput (Text).
Initialize SubmissionStatus = SUBMISSION_UNCONFIRMED and SuccessScreenshotPathOutput
empty at the beginning so no earlier run's success can leak into a new run.

Derive ExpectedReturnPeriod and ExpectedSavedReturnName from the supplied TIN and
period exactly as before. In the verification If, compare them to
ApprovedReturnPeriod and ApprovedSavedReturnName, not literal test values.
Require ExpectedFormNumber = 2551Qv2018, nonempty WorkOrderId/ApprovalId/ApprovedBy,
ApprovedForSubmission = True AND SubmissionEnabled = True before Submit / Final Copy.
For the existing If action, use this First operand (Equal to, True):
```
%IsNotEmpty(WorkOrderId) AND IsNotEmpty(ApprovalId) AND IsNotEmpty(ApprovedBy) AND ApprovedForSubmission = True AND SubmissionEnabled = True AND ExpectedFormNumber = '2551Qv2018' AND ExpectedReturnPeriod = ApprovedReturnPeriod AND ExpectedSavedReturnName = ApprovedSavedReturnName%
```

Require exactly one XML matching the derived name, and require its full path equals
ApprovedXmlPath. Verify the opened return identity before submission using the
existing exact saved-row matching. No operator should type fake approval values.

After Submit / Final Copy, wait for and click the confirmation OK, then wait for
and click the Terms of Service Ok. Wait for the exact success message before
recording success. Set a finite timeout (120 seconds for success).
Save the screenshot to %SuccessScreenshotPath%, replacing the old fixed filename.
Only after screenshot save succeeds:
- Set SuccessScreenshotPathOutput = %SuccessScreenshotPath%
- Set SubmissionStatus = SUBMITTED_WAITING_FOR_CONFIRMATION
Then close success/ePay/form as tested. A cleanup failure must preserve this success
status and screenshot; it must not cause another submission.
If submission may have started but success was not observed, keep
SUBMISSION_UNCONFIRMED. Use FAILED_SYSTEM only for known pre-submission failures.
Never automatically retry Submit after timeout. Return outputs to the parent.

## 3. Connect the existing agent wrapper

Inside its existing If Job['HasTask'] = False block, before Wait/Next loop:

Run PowerShell (output Stage2Response):
```powershell
& ([scriptblock]::Create([IO.File]::ReadAllText('C:\TaxAutomation\Stage2Bridge.ps1'))) -Action Poll
```
Convert Stage2Response JSON to Stage2Job.
- If RecoveryRequired = True: stop and review; preserve journals.
- If HasTask = False: retain the existing Wait/Next loop.
- If HasTask = True: require AutomationKey = SUBMIT_2551QV2018. An old rehearsal
  job must go to a separate disabled-submit flow, never to the live child.

Run the same script with -Action Start, convert response to Stage2Start and require
Started=True. It checks approval mode, the approved PDF hash, XML presence and a
fresh screenshot destination. It journals Running before the desktop flow starts.

Run desktop flow Stage2_Open_Approved_Return, waiting for completion. Map EVERY
input above to %Stage2Job['Inputs']['INPUT_NAME']%. Map outputs SubmissionStatus
to Stage2SubmissionStatus and SuccessScreenshotPathOutput to Stage2ScreenshotPath.

Set Stage2Result to this PAD custom object:
```
%{'AttemptId': Stage2Job['AttemptId'], 'SubmissionStatus': Stage2SubmissionStatus, 'SuccessScreenshotPath': Stage2ScreenshotPath}%
```
Convert Stage2Result to JSON (Stage2ResultJson), retrieve LOCALAPPDATA if necessary,
and overwrite %LocalAppDataPath%\TaxAutomationWorker\stage2-result.json with it.
Run the bridge with -Action Publish and inspect the returned Status. Publish uploads
PNG evidence and records the result. After successful live reporting it archives
the approved XML using Archive-SubmittedReturn.ps1. The child must close the return
before returning. Install the helper and updated WorkerBridge.ps1 as documented in
[Submitted XML archiving](submitted-xml-archive.md). Archive failures leave the
submission recorded and require archive-only recovery; never rerun the child.
Failed uploads can retry Publish with the SAME
journal/result; never rerun the child. For an uncaught child failure, stop with the
journal intact and investigate whether transmission happened before reporting.

## 4. Dashboard

Review the PDF, check the explicit submission authorization, then Approve & submit.
Only the same worker that prepared the return can claim it. Approval is bound to the
snapshot and PDF hash, and a taxpayer/period with another live approval is blocked.
The dashboard displays the Stage 2 status and a private screenshot link after upload.
Receipt email monitoring and final-package generation are implemented; see [the receipt guide](bir-receipts.md). The legacy work-order status
tracks preparation; Stage2Approval tracks submission and drives displayed status.
Expired leases (30 minutes) and interrupted runs require operator review. Renew is
available for long-running operations. Never delete journals to restart a live run.

## Validation

Backend tests cover approval modes, permissions/CSRF, exact identities, evidence,
result replay and unconfirmed attempts. Windows integration exercises both bridge
modes against an isolated local server, including PNG upload; it does not submit to
BIR. Code tests do not replace verification of the installed PAD mapping. Recheck affected routes/selectors after any desktop-flow change.
