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
## Worker restart follow-up

A later restart stopped at preflight because the runtime profile patch could not be verified after the leftover eBIRForms window was closed. No new job was claimed by that blocked run. Ran the existing hash-verified Restore-eBIRFormsRuntimeIfMissing helper while PAD and eBIRForms were idle; 0619E, 0619F, 1601EQ, and 1601Cv2018 all reported PATCHED. Restarted only eBIR_Work_Order_Agent. It passed preflight, claimed an approved 0619E job, and refreshed HYPERV-EBIR's server heartbeat. The earlier unconfirmed 1601C attempt was not retried. Runtime restoration is local installation recovery, not proof that the external BIR transmission issue is resolved.

## 0619E transmission diagnosis

The next approved 0619E run displayed "Your Tax Return was not submitted online" and timed out waiting for success. No retry was made. Hidden sender files (ebfSFTP.exe, its config, WinSCP.exe and WinSCPnet.dll) match the original installer; they are not missing. The primary BIR dispatcher responds and supplies SFTP port 22. The configured host ebf2.bir.gov.ph resolves to 87.121.117.111, but a TCP connection to port 22 times out from both the Windows worker and server VM. This narrows the failure to shared networking or the remote service; it does not prove which side is responsible. No firewall, endpoint, credentials, or tax data were changed.

The failed attempt's local result was set to SUBMISSION_UNCONFIRMED. Publish returned REPORTING_RECOVERY_REQUIRED with an underlying HTTP 409; its journal remains pending for reporting reconciliation. Do not rerun submission to resolve reporting. Check receipt evidence and reconcile the attempt before resuming it. A successful tax transmission has not been verified.

## Continue pending preparation

On user authorization, reconciled the exact expired 0619E attempt transactionally as FAILED / SUBMISSION_UNCONFIRMED, retained the attempt and XML, released its execution slot, and added an audit event and evidence note. Retried Publish only; the server acknowledged SUBMISSION_UNCONFIRMED and the local journal completed. Enabled PreparationOnly with a timestamped configuration backup. Five READY_TO_PREPARE orders were present when checked. Restart was blocked by desktop input returning Access is denied and a black capture; no additional submission or preparation was launched. Bounded submission retries have not been implemented; preparation-only is the immediate workaround while SFTP remains unavailable.
