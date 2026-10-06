# 1600VT preparation integration

Preparation only: non-amended, private withholding agent, no tax withheld,
attachments, relief, credits or penalties. Submission is disabled.

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
Do not add a Stage 2 branch.

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
