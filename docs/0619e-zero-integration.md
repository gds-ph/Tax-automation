# 0619-E zero preparation

Deployed and verified end to end on 11 October 2026. Stage 1 preparation and Stage 2 submission routing are installed. The Stage 2 open-and-validate rehearsal passed; actual BIR submission and post-submit UI handling have not been exercised for 0619E.

The existing `cor_0619e` catalog entry is upgraded in place to `0619e_zero`, retaining existing client filing profiles. Migration 0026 defaults availability off. The live catalog was enabled through the audited catalog service after the PAD route and worker capability were installed.

The monthly preparation page requires zero confirmation, offers months 01, 02, 04, 05, 07, 08, 10 and 11, and removes automatic submission. The model independently rejects quarter-end months, nonzero filings and nonempty form data. The existing nonzero transaction worksheet remains a separate draft workflow.

## Worker contract

- Key: `PREPARE_0619E_ZERO`.
- PAD: `Stage1_Prepare_0619E`, ID `61370ebd-3fad-465a-adf0-8ee7ac94adf2`.
- Main worker: 109 actions, with existing routes retained; 21 child inputs and three outputs mapped.
- XML: `<TIN>-0619E-<MM><YYYY>.xml`, without the 0619F `WB` suffix.
- PDF: `<ClientNameSafe>_0619E_<YYYY>_<MM>_COMPLETE.pdf`, exactly one page.
- Completion: `AWAITING_SUBMISSION_APPROVAL`, which represents an unsubmitted local draft.
- Existing output files block preparation; the bridge maps that result to a business failure without uploading old files.
- Before publishing a successful result, `Test-0619EPreparedXml.ps1` verifies exact client/period fields, zero amounts, original/private/no-withholding selections, WME10/WE and final flag 0. Missing, duplicate or mismatched verification fields stop publishing.

## Evidence

The user-visible dashboard queued Test Company (dummy TIN 63984860500000), August 2026. Work order `806f0de4-92e6-4c1f-9c17-ea9b1d2e33d6` reached `AWAITING_SUBMISSION_APPROVAL`, version 6, with its prepared PDF visible under Documents. The worker completed the journal and returned to polling. No BIR submission was performed.

Local checks: 50 selected preparation/worksheet/regression tests passed before narrowing incidental test discovery; no migration drift. The deployed image passed 18 focused 0619E and worksheet tests. The XML helper accepted the real rehearsal XML and rejected six deliberate mutations (wrong taxpayer, period, amount, submitted flag, withholding flag, duplicate field). A broad server test discovery also picked up an unrelated existing 2551Q PDF iframe assertion that differs from the deployed Documents UI; the 0619E test module now imports helper methods without collecting that unrelated test class.

## Backups

- Server: `/home/nodeadmin/ebir-deployment/backup-0619e-integration-20261011T134411Z`, containing source and SQLite backups plus prior image identity. SQLite backup integrity check returned `ok`.
- Windows bridge: `C:\TaxAutomation\Backup-0619E-20261011-214526`.
- Private worker configuration backup stays beside `worker.json`; credentials were preserved and not exported.
- Parent PAD source backup: workspace `work/agent-before-0619e.pad.txt`.

The deployment preserved server-specific source differences and restarted only the web container. Existing client profiles for real taxpayers were not added or changed; only Test Company's 0619E test card was added. Other clients can use their existing upgraded card or have a 0619E card added through the normal reviewed setup workflow.


## Stage 2 update (11 October 2026)

- PAD `Stage2_Submit_0619E`, ID `df2dbd56-c5c3-42af-85c8-28339b0e9048`, saved with 77 actions. Main worker now has 113 actions and passes the existing 23 inputs / two outputs.
- Exact approved XML filename/path selects the saved-return radio button dynamically, without OCR or the 0619F WB suffix. Approval, form, period and filename checks precede opening; validation requires the exact success message.
- Bridge validates the zero XML again before starting; duplicate-run journals, approved PDF hash, screenshot evidence and archive rules remain in force.
- Non-submitting August sample rehearsal returned `REHEARSAL_VALIDATED_NOT_SUBMITTED`. Test inputs and forced stop were removed and the reusable flow saved. XML verified afterward with final flag 0. No approval or BIR submission was created.
- Seven focused tests passed locally and in the deployed image. Server web healthy; Windows bridge health okay. `ENABLE_0619E_SUBMISSION=1` now exposes manual Approve & submit. Auto-approval remains absent from the 0619E preparation form.
- Post-submit selectors were adapted from the existing monthly flow and checked against installed 0619E source. Live BIR response, screenshot capture, publishing and archive have NOT yet been tested for this form.
- Server backup: `/home/nodeadmin/ebir-deployment/backup-0619e-stage2-20261011T144139Z`; previous image `ebir-server-app:before-0619e-stage2`. Private environment backup beside `.env.server`. No schema change.
- Windows backup: `C:\TaxAutomation\Backup-0619E-Stage2-20261011-224138`. Private config backup beside worker.json. Parent backup: `work/agent-live-before-e-stage2.pad.txt`.
- Do not approve the dummy Test Company return for a live BIR submission.
