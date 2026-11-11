# Filing retry recovery — 2026-11-11

User requested recovery of three October 2026 failures. Retried only the specified failed records, preserving their previous attempts and audit history. Read-only mailbox checks found no matching receipt before each retry. A missing receipt alone was not treated as proof of failure: the two submission failures had previously displayed eBIRForms' explicit not-submitted dialog.

## Saved PAD fixes

- Stage2_Submit_1601C: added Enabled-property guard around Validate and its OK action. Then replaced unfocused dropdown typing with control-targeted Home/type/Tab selection for RDO and form. Added normal-versus-resend confirmation handling and both verified success messages. Saved 82 actions; exact action export verified and Designer returned Ready.
- Stage2_Submit_0619E: added the same validation guard; reads confirmation text and permits only the normal submission or resend prompt; skips the terms screen for resend. Reads result text and requires either the normal success sentence or resend success phrase, plus the email-notification sentence. Other results remain SUBMISSION_UNCONFIRMED. Removed the brittle payment Close wait/click; the final window-close action remains. Saved 94 actions with no Designer errors.
- 0619E confirmation/result text selectors now identify dialog Static text without an exact Name constraint; the flow explicitly checks that text before proceeding or recording success. PAD renamed these selectors with a `2` suffix during import. Both exported selector definitions and all action text were verified after accounting for this rename.

Action-only snapshots are under docs/pad-actions. Full before/after exports remain local under C:\TaxAutomation-work\Stage2_Submit_<form>.*-retry-20261111.txt because UI repositories contain screenshots. These action-only snapshots do not replace the saved flow's UI repository.

## Recovery evidence

The 1601C retry transmitted successfully, but the existing post-submit path still waited for a terms-screen control that resend does not show. Observed the full eBIRForms Submit Successful! dialog, saved its full-window screenshot, converted the capture from JPEG to PNG without changing its content, and published the existing attempt's success evidence through the worker API. Retried result reporting only, never submission. Server acknowledged SUBMITTED_WAITING_FOR_CONFIRMATION and Stage2Bridge archived the XML. The final dropdown/resend improvement was subsequently saved. Its new complete normal-submission path subsequently passed the approved corrected-PDF retry described below; the earlier resend success was recovered by publishing observed evidence.

For the preparation failure, verified the truncated-name PDF contained only one page. Preserved the PDF and moved the exact unsubmitted XML to a hash-verified local recovery backup before re-preparation. Reclassified the reviewed existing-file business failure as the original system/print failure, added an audit event, and used retry_preparation to queue the unchanged snapshot. This prepares a PDF for review; it does not approve a newly prepared return for submission.

Restored the extracted eBIRForms runtime while idle using the existing hash-verified helper; all four required form patches reported PATCHED. No security settings, tax amounts, taxpayer identities, or external service credentials were changed.

## Verification status

- 1601C submission: server success recorded; awaiting receipt confirmation at that observation.
- 0619E: repaired flow completed a monitored retry end-to-end; full success screenshot uploaded and server recorded SUBMITTED_WAITING_FOR_CONFIRMATION.
- Failed preparation: regeneration completed, but verification found two copies of logical page 1. Recovered logical page 2 directly from the unchanged saved return and merged page 1 followed by page 2 and its continuation. All three physical pages were rendered and inspected. The corrected PDF was subsequently approved, installed and submitted successfully as described below. The subsequent submission attempt reported SAVED_RETURN_ROW_NOT_FOUND, before opening/submitting the return; its history is preserved.

This is an operator-authorized recovery, not an unlimited automatic retry loop. Unconfirmed outcomes still require evidence review before another submission.

## Additional print and preflight corrections

- Stage1_Prepare_1601C: replaced Populate/Enter for the print-preview page selector with focused hardware Ctrl+A, 2, Tab, so the HTA key-up handler changes the displayed page. Reversed the old Page2/Page1 merge order to Page1/Page2. Saved 179 actions; exact export verified, no Designer errors. Manually exercised the same page-number key sequence against the saved return and observed the displayed page change. A full new preparation run has not been performed after this last correction.
- The corrected output contains three physical pages, which the existing 1601C server validator permits: logical page 1, logical page 2, and the instruction continuation. No tax amounts were changed.
- Assert-0619EPreparedXml now accepts final flag 2 only when the approved Stage2Bridge call supplies AllowFailedSubmissionRetry. Preparation still requires flag 0. Success/offline flags, missing/duplicate flags, identity mismatches and amount mismatches remain rejected. This does not authorize automatic retries of unknown submission outcomes.
- Runtime Stage2Bridge.ps1 and Test-0619EPreparedXml.ps1 were patched locally with backups. Existing runtime-only decoding differences were preserved rather than replacing the complete files with repository copies.
- Nine offline synthetic-fixture checks passed (fresh preparation, approved failed retry, and seven rejection/guard cases). Existing test-pad-repair-snapshot.cjs passed. These tests do not run PAD or transmit returns.

## Local recovery exports

Full before/after exports are retained under C:\TaxAutomation-work:

- Stage2_Submit_1601C.before-lookup-20261111.txt and .after-lookup-20261111.txt
- Stage1_Prepare_1601C.before-page2-20261111.txt and .after-page2-20261111.txt
- Stage2_Submit_0619E.before-retry-20261111.txt and .after-retry-20261111.txt

The corrected taxpayer PDF, original artifacts, XML backup, UI repositories, credentials and journals are intentionally not committed to Git. Action snapshots require their associated saved PAD UI repositories; they are not standalone import packages.

## Corrected-PDF approval and successful retry

After explicit user approval on 2026-11-11, installed the corrected three-page PDF as a new stored artifact and updated the approval to its exact SHA-256. Preserved the old PDF and all attempt history. Recorded PDF replacement and approval audit events; the amount due remained PHP 775.65. Used the normal saved-return lookup recovery service to queue the reviewed failure.

The new 1601C attempt completed end-to-end through the repaired flow at 06:15:26 UTC. Verified the full-screen eBIRForms "Submit Successful. Subject to validation by BIR." evidence, server attempt SUCCEEDED, approval SUBMITTED_WAITING_FOR_CONFIRMATION, and archived XML plus archive manifest. The local Stage2 journal is Completed. This confirms transmission and evidence capture, not receipt confirmation or payment.

A temporary form-scoped worker configuration selected this retry without changing the main worker configuration. The parent worker continued processing its existing queue afterward. Taxpayer artifacts and temporary credential-bearing configuration remain local and are excluded from Git.
