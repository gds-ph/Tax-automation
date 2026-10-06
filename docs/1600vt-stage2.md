# 1600VT Stage 2 setup

Server support uses SUBMIT_1600VT and is gated by ENABLE_1600VT_SUBMISSION=1.
The switch remains OFF until the child flow and parent routing are verified.
Do not use placeholder approvals or enable submission flags for manual testing.

## Parent flow (Stage 2 section near the top)

Inside the nested unsupported-key checks, add another If before Stop flow:
Stage2Job['AutomationKey'] <> 'SUBMIT_1600VT'. Put Stop flow inside it.

After the SUBMIT_0619F branch, before the final Else, add Else if:
Stage2Job['AutomationKey'] = 'SUBMIT_1600VT'.
Run Stage2_Submit_1600VT with Wait for flow to complete enabled.
Use Stage2Job here, not the preparation Job variable.

For each input below, use %Stage2Job['Inputs']['INPUT_NAME']%:
ApprovedForSubmission, SubmissionEnabled, WorkOrderId, ApprovalId, ApprovedBy,
TIN1, TIN2, TIN3, TIN4, RDOCode, FormSelectionText, FormCode,
ExpectedFormNumber, FilingYear, FilingMonth, FilingQuarter, YearEndMonth,
ApprovedReturnPeriod, ApprovedSavedReturnName, ApprovedXmlPath,
SuccessScreenshotPath.

Special mappings:
ExpectedReturnPeriod = %Stage2Job['Inputs']['ApprovedReturnPeriod']%
ExpectedSavedReturnName = %Stage2Job['Inputs']['ApprovedSavedReturnName']%

Outputs must feed the existing publisher:
SubmissionStatus -> Stage2SubmissionStatus
SuccessScreenshotPathOutput -> Stage2ScreenshotPath

## Child flow requirements before activation

ExpectedFormNumber must be 1600VTv2018. Filename is TIN-1600VTv2018-MMYYYY.xml.
Keep exact approved XML path, filename and period checks. Approval flags default
False, and IDs/approved values have no hardcoded test defaults.
Read the opened return's TIN and month/year and compare with the job BEFORE
Submit / Final Copy; OCR row selection alone does not verify the opened return.
Wait for the specific validation-success message and fail on timeout.
Wait for the specific submission-success message and fail on timeout.
Focus the success dialog window (not its text element), save the screenshot,
and only then report SUBMITTED_WAITING_FOR_CONFIRMATION.
An uncertain submission result must not be automatically retried.

## Install

Stop both PAD flows. Extract the package on the PAD computer, open PowerShell in
that folder, then run:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-1600VT-Stage2.ps1

The installer preserves credentials, journals and existing capabilities, backs up
the installed files and adds SUBMIT_1600VT. It does not enable the server switch
or create an approval. Save the parent changes before restarting it.

After routing and child checks are verified, enable the server switch and review
an actual prepared filing through the dashboard. Approval supplies all matching
values automatically. No live submission was performed during integration tests.
