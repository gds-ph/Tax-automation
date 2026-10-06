# 0619-F zero-filing PAD integration

Current status, 2 October 2026: preparation and Stage 2 code/routes are implemented; preparation is enabled and `ENABLE_0619F_SUBMISSION` was verified True on the server. Earlier dated sections below preserve the investigation and rollout history and are not current disabled-state instructions. Use [preparation recovery](worker-preparation-recovery.md) for interrupted runs.

Status (30 September 2026): local Stage 1 rehearsal verified; parent PAD route and VM capability configured; dashboard preparation enabled for the end-to-end test. Dashboard-to-worker preparation test remains pending. Submission remains disabled. Earlier planning sections below describe the initial investigation.

## Scope

0619-F (Monthly Remittance Form of Final Income Taxes Withheld), zero filing only. Do not reuse 0619-E or 1601-C form selectors. Do not submit the rehearsal.

Official form reference: https://bir-cdn.bir.gov.ph/local/pdf/0619-F%20Jan%202018%20rev%20final.pdf
Official instructions: https://efps.bir.gov.ph/efps-war/EFPSWeb_war/forms2018Version/0619F/0619f_guidelines.html

## Desktop evidence needed

- Screenshot of the installed eBIRForms form-selection entry and the opened 0619-F form, including the lower fields and buttons.
- A dummy return saved locally, with its exact XML basename and period format. Do not infer the version suffix from another form.
- Current Stage1_Prepare_1601C PAD actions and input/output definitions for use as a monthly-flow scaffold; recapture form-specific selectors.
- Verify the zero-return selections, validation result, saved-return reopening and PDF output on the installed version.

## Proposed flow names

- Stage1_Prepare_0619F: open the correct form, populate reviewed identity and monthly period, set verified zero-return values, validate, save and print to PDF, return existing preparation outputs.
- Stage2_Submit_0619F: implement only after preparation is verified; preserve exact identity matching, approval checks, screenshot and result reporting.
- Proposed preparation route: PREPARE_0619F_ZERO. This is a proposed key, not currently advertised by a worker.

## Integration work after desktop verification

1. Add the form definition and catalog entry with verified identity/filename rules and zero-only validation.
2. Add the dashboard filing card and monthly preparation support.
3. Extend worker input validation and bridge allowlists; enable the capability only after the parent route and child flow exist.
4. Verify a prepare-only dummy run and inspect the XML and PDF before allowing submission.
5. Reuse receipt matching, missing-TRRC escalation and final-package archiving after tracked submission. Preserve the existing BIR / FILED RETURNS destination selection.

No existing flow, worker capabilities or live filing settings were changed by these notes.

## Supplied completed example reviewed

Source: `0619F JULY_2026 NETRON INFORMATION TECHNOLOGY INC.pdf` (two pages), read-only review.

- Page 1: January 2018 0619-F layout; filing month 07/2026; printed due date 08/10/2026. This observed date is not a general due-date calculation rule.
- Amended form: No. Any taxes withheld: No. Withholding-agent category: Private. Tax type code: WB.
- Items 13 (WMF10) and 14 (WMF20): zero. Items 15?17, penalties 18A?18D, and total 19: zero. Payment and signature fields are blank in the example.
- Page 2: TRRC names `662194954000-0619F-072026WB.xml`. The printed form has a 9-digit TIN plus a 3-digit branch. Do not assume the existing 14-digit filename convention applies or silently truncate a supplied branch code.
- TRRC reports receipt by BIR on 18 August 2026 at 11:02 AM; its email header shows 11:55 AM. Preserve the distinction between BIR receipt time and email timestamp.
- The example's WB suffix is absent from existing generic receipt filename acceptance. This must be explicitly handled and tested before enabling 0619-F tracking.

Still needed: installed desktop screenshots/selectors and an actual locally saved XML filename/content (sensitive values may be replaced consistently) to verify the automation contract. The PDF/TRRC establishes an example, not tested PAD selectors or proof of tax validation.

## Stage 1 local rehearsal (30 September 2026)

The operator captured 0619-F selectors in the duplicated `Stage1_Prepare_0619F` PAD child. The exported selector IDs included `frm0619F:txtYear`, `frm0619F:txtMonth`, `frm0619F:optAmend:N`, `frm0619F:optWithheld:N`, and `frm0619F:optCategory:P`. Item 5 WB is disabled when Any Taxes Withheld is No; the flow does not force it. The flow prints one page directly to `_COMPLETE.pdf` and uses a saved XML path ending `-0619F-<MM><YYYY>WB.xml`.

An isolated dummy run produced `Test_Company_0619F_2026_01_COMPLETE.pdf` and a newly modified `63984860500000-0619F-012026WB.xml`. The resulting PDF displays 0619-F, January 2026, WB, No withholding, and Private. PAD output `PreparationStatusOutput` was `AWAITING_SUBMISSION_APPROVAL`. These observations verify local Stage 1 preparation and do not imply that the parent routes, dashboard capability, Stage 2, or submission are ready.

App code contains the zero-only form definition, one-page PDF rule, exact WB filename handling, and a catalog migration that defaults preparation to disabled.

## Parent and worker integration (30 September 2026)

The operator added the nested allowed-key guard and the PREPARE_0619F_ZERO dispatch to Stage1_Prepare_0619F, mapped the Job Inputs, and bound the child results to PreparationStatusOutput2, PreparedPdfPath2, and SavedXmlPath2 used by the parent result object. Existing Start/Publish steps remain present.

The VM bridge and private worker configuration were backed up and updated. Read-back checks returned ConfigKeyCorrect=True, BridgeKeyCorrect=True, and KeysWithBackslashes=0.

The live catalog was enabled for preparation through catalog_services.update_record using the admin actor, producing catalog version 2 and an audit event. No queued or processing 0619-F orders existed at activation. Submission remains disabled. Enabling preparation is required to create the dashboard rehearsal; it is not evidence of a completed end-to-end test.

Next: use a dummy client for one dashboard preparation, compare expected and returned XML/PDF paths, inspect the uploaded PDF, and verify AWAITING_SUBMISSION_APPROVAL. Stage 2 remains unimplemented and unverified.

## Stage 2 integration (1 October 2026)

Operator evidence: the child opens the February dummy saved return, validates it, and uses a 0619-F dialog selector containing `Submit Successful!`. Parent SUBMIT_0619F guard/dispatch and Stage2SubmissionStatus/Stage2ScreenshotPath bindings were reviewed. This does not establish a successful approved dashboard submission.

Server code now supports SUBMIT_0619F, approval-bound MMYYYY and WB filenames, and a default-off ENABLE_0619F_SUBMISSION flag. The Stage2Bridge and archive helper accept this key. The dashboard work-order filter includes 0619F. No submission approval or live filing was created during integration.

Validation: 43 form/API tests and 65 Stage 2/Windows bridge tests passed, including an isolated 0619F HTTP/PowerShell preparation-to-approval-to-evidence-to-archive/replay test. Django checks and migration drift checks passed. No test contacted BIR.

VM package: dist/0619F-Stage2/0619F-Stage2-Update.zip. Stop the parent flow between tasks, extract to a separate folder, and run Install-0619F.ps1 as the PAD Windows user. It backs up installed bridges and private configuration, preserves existing capabilities and credentials, and adds PREPARE_0619F_ZERO / SUBMIT_0619F. VM installation remains pending. The server live-submission switch remains off pending installation and the dashboard preparation review.

User requested live enablement on 1 October 2026 after the VM installer and dashboard preparation succeeded. ENABLE_0619F_SUBMISSION=1 was persisted in the server environment and containers recreated. The live-availability property was verified. No approval or submission was created. The legacy catalog submission boolean remains constrained False and is not used by the Stage 2 approval gate.
