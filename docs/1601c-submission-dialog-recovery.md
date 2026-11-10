# 1601C Stage 2 result-dialog recovery (2026-11-10)

The submission attempt displayed eBIRForms' "Your Tax Return was not submitted online" message. The generic dialog selector also matched this failure message, so the flow incorrectly assigned SUBMITTED_WAITING_FOR_CONFIRMATION and then timed out waiting for the form's Close button.

The stopped attempt was published as SUBMISSION_UNCONFIRMED using Stage2Bridge. Its XML and local screenshot were retained; it was not resubmitted or archived. The screenshot filename alone is not evidence of success.

## Saved PAD change

Stage2_Submit_1601C now reads the dialog's Own Text. Both "Submit Successful." and "Subject to validation by BIR" must occur before assigning the success status and screenshot output. Other messages retain the default SUBMISSION_UNCONFIRMED status. The screenshot is still captured before dismissing the dialog. The brittle wait/click for the form's Close button was removed; the existing window-close action remains.

The action-only export is in pad-actions/Stage2_Submit_1601C.actions.txt. UI repository metadata remains in the saved PAD flow, not Git.

## Verification and limits

PAD accepted all 70 actions with Ready status and no visible Designer errors. Re-exported action text matches the candidate exactly. The saved flow has not yet been validated by a fresh successful BIR submission. This fixes result handling; the eBIR message does not identify whether the underlying transmission failure was internet connectivity, slow connection, firewall, or a remote service failure. No security settings were changed.

Local full backups (not committed because UI metadata may contain taxpayer screenshots):
- C:\TaxAutomation-work\Stage2_Submit_1601C.before-dialog-fix-20261110.txt
- C:\TaxAutomation-work\Stage2_Submit_1601C.after-dialog-fix-20261110.txt

Before retrying the unconfirmed filing, reconcile BIR receipt/email and saved-return state. Do not automatically submit it again.