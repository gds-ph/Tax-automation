# 1600VT preparation integration

This guide covers preparation: non-amended, private withholding agent, no tax
withheld, attachments, relief, credits or penalties. Submission is a separate
installation and approval flow; see [1600VT Stage 2](1600vt-stage2.md).

The PAD flow must be named Stage1_Prepare_1600VT. In the parent worker, add an
Else if branch alongside the existing preparation branches:
Job['AutomationKey'] = 'PREPARE_1600VT_ZERO'.
Run Stage1_Prepare_1600VT with inputs from Job['Inputs']:
TIN1, TIN2, TIN3, TIN4, RDOCode, RegisteredName, RegisteredAddress, ZipCode,
TelephoneNumber, EmailAddress, LineOfBusiness, FormSelectionText, FormCode,
FilingYear, FilingMonth, ClientNameSafe, OutputFolder.
FilingYear is four digits; derive FilingYearShort inside the child flow for the
form's two-digit input. FilingMonth is two digits.
Map PreparationStatusOutput, PreparedPdfPath and SavedXmlPath back to the same
parent variables used by the existing common preparation publishing step.
PAD may generate suffixed variables; explicitly map/copy them before publishing.
Do not change Stage 2 routing as part of this preparation setup.

The XML filename is TIN-1600VTv2018-MMYYYY.xml (no WB suffix).
The PDF filename is ClientNameSafe_1600VT_YYYY_MM_COMPLETE.pdf.
The API accepts a one-page PDF; visually check the whole page is present.
Use the supplied OutputFolder to isolate each attempt. Existing-file checks
alone do not prove freshness; confirm the saved XML is from this run.

Stop the parent flow, save the new PAD branch, then run Install-1600VT.ps1 from
the update package as the PAD Windows user. It backs up and updates WorkerBridge.ps1,
adds PREPARE_1600VT_ZERO to worker.json, and preserves credentials, other
capabilities, Stage 2 and journals. Enable the catalog preparation flag only after
this routing is installed. Restart the parent worker and queue one test filing.
Verify the uploaded PDF and reported XML path before using real clients.

## Preparation enhancement, 15 October 2026

The installed child flow has 109 actions. The original 85-action export is
preserved outside Git; see [PAD inventory](pad-release-inventory.md).

- TIN and profile fields use simulated population instead of character-by-character
  entry. The four TIN segments are read back and compared before continuing.
- Name, address, postal code, telephone, email and business description are refreshed
  from the work order even when eBIRForms loads a cached client profile.
- An existing target XML stops preparation before opening eBIRForms, preventing a
  rerun from overwriting an existing return.
- The printer is selected directly; the print confirmation uses a bounded element
  wait. Form selection retains the original keyboard method because this eBIRForms
  dropdown did not support PAD selection by option name reliably.
- `WorkerBridge.ps1` requires `Test-1600VTPreparedXml.ps1` alongside it. Before upload,
  the helper verifies TIN, RDO, registered name (normalized to uppercase by eBIRForms),
  email, period, filing flags, empty ATC rows and zero amounts. Missing or duplicate
  verification fields stop publication. The 1600VT installers include this helper;
  copy it as well when updating the bridge manually.

Test Company 2, July 2026, work order `600fa78d-f647-47f0-b1f9-10c0e0167c3c`:
PAD generated the one-page PDF and XML; both were inspected. The final attempt
`d28c820b-9704-429f-aa7f-23337f5dd5fb` reached `AWAITING_SUBMISSION_APPROVAL`.
Publication was retried without rerunning PAD after correcting the validator's
uppercase-name normalization. No submission was performed. Two earlier attempts
stopped at dropdown selection and were released through the recovery service.

Validation: 30 existing 1600VT tests passed. The XML helper accepted a valid test
return and rejected wrong-period, nonzero-amount, missing-field and duplicate-field
variants. A before/after timing benchmark was not performed; reduced typing and
one replaced fixed wait do not establish an end-to-end speed guarantee. New-client
registration and live submission were not exercised by this enhancement test.
