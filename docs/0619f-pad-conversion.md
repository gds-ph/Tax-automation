# Convert the copied Stage 1 flow to 0619-F

> Historical record. Reviewed 2 October 2026: implementation status, permissions, addresses and test counts below refer to the original delivery, not the current deployment. Start with the [current documentation index](README.md). For recovery use [the current guide](worker-preparation-recovery.md); do not replay old reset instructions against a new attempt.

Status: reviewed action mapping; requires UI capture and local rehearsal in PAD. Not an executable replacement flow. Edit only the duplicated `Stage1_Prepare_0619F` flow. Leave the working 1601-C flow intact.

Source: user action export supplied 29 September 2026. Line references below refer to its action text, starting at `System.RunApplication.RunApplication`, before the control repository. PAD action numbers may differ because the text contains multiline actions and disabled blocks.

## 1. Open the correct form

Keep the application launch and main-window identity-entry logic as the starting point (text lines 1?35). Set this duplicate's FormCode to `0619F`. Set FormSelectionText to the exact 0619-F entry shown in the installed eBIRForms list; its precise spelling must be observed rather than guessed.

The first form-specific action is line 36, a wait targeting `BIR Form No. 1601Cv2018`. Replace its UI element with a newly captured element from the actual 0619-F window. Recapture all subsequent form-specific elements, including print/save dialogs parented under that window. Renaming a UI element or changing only its displayed window label does not establish correct selectors.

The main-window `Submit` action at line 27 occurs in the new-profile setup branch. Inspect that dialog to confirm its purpose before retaining it; it is not evidence that the Stage 1 flow should submit a tax return. No Submit / Final Copy action belongs in this preparation rehearsal.

## 2. Replace the 1601-C input block

| Existing action | 0619-F replacement |
| --- | --- |
| Line 38, Edit 2 with FilingYear | Capture the filing YEAR field in item 1, not the due-date year in item 2 |
| Lines 39?40, month selector and FilingMonth | Capture the item 1 month dropdown; use FilingMonth |
| Line 57, No radio | Capture item 3 Amended Return: No |
| Line 58, Edit 3 = 0 | Remove; this is the old 1601-C attachment-field action |
| Line 59, second No radio | Capture item 4 Any Taxes Withheld: No |
| Line 60, Private | Capture item 11 Private |
| Line 61, third No radio | Remove; the 1601-C tax-relief question is absent from this 0619-F layout |
| New action | Capture item 5 Tax Type Code and select WB for the agreed sample scope |

Remove the disabled 2551Q quarter-switch, ATC and page-navigation blocks from the duplicate. WMF10 and WMF20 are fixed printed remittance rows on this form, not the old quarterly ATC selection workflow.

Inspect zero values in items 13, 14, 16, 18A, 18B and 18C. Verify calculated items 15, 17, 18D and 19 are zero. Never assume a previously opened return was blank. Do not overwrite calculated or disabled controls. Confirm company/TIN/branch/RDO and period match the intended test inputs.

Item 2 is a separate due-date field: verify what the installed application derives and which fields are editable; do not type FilingYear into it or infer a universal deadline from the supplied example.

## 3. Validate and save

Recapture Validate and Save plus their actual dialogs (old lines 73?80). Wait for each expected dialog and check its message. A generic OK click must not treat a validation error as success. Stop on errors or an unexpected saved-return collision.

First rehearsal ends after a successful local Save. Inspect the exact XML filename in `C:\eBIRForms\savefile` and record it before implementing the output path. Do not publish a standalone rehearsal as a dashboard job.

The older supplied TRRC names `662194954000-0619F-072026WB.xml`. The current screenshot has five branch digits. Therefore the old line 116 path is not verified: it omits WB, and branch length must be confirmed from the current installation. Preserve all digits and never silently shorten a branch.

## 4. Print one form page

Recapture the form Print button and print-preview window. Retain the Microsoft Print to PDF approach only after its dialogs are verified.

Change the first PDF destination (old line 95) to:

`%OutputFolder%\%ClientNameSafe%_%FormCode%_%FilingYear%_%FilingMonth%_COMPLETE.pdf`

Remove the page-2 navigation, second print and Pdf.MergeFiles block (old lines 98?110). The supplied example has one 0619-F form page; its second PDF page is the later TRRC email and is not part of Stage 1 printing. Inspect the generated PDF for clipping or overflow before declaring the print flow verified.

Keep PreparedPdfPath pointing to this COMPLETE.pdf. Recapture the form close-window selector. Change the missing-PDF message from 'merged review PDF' to 'review PDF'.

## 5. Output and parent integration

Preserve `PreparedPdfPath`, `SavedXmlPath`, and `PreparationStatusOutput` output variables. Initialize failure status and clear stale output paths before preparation. Success requires the current run's validated form, verified XML identity and generated PDF; existence of old files alone is insufficient.

The parent route, worker capabilities, backend definition and receipt filename acceptance still require implementation after the local contract is verified. Do not advertise PREPARE_0619F_ZERO to a running worker yet.

## Next evidence needed

After changing form selection and recapturing the opening wait, open 0619-F with dummy inputs and capture its item 1 month/year, item 3 No, item 4 No, item 5 WB, and item 11 Private controls. Supply the revised action export and the actual saved XML filename after a successful Validate/Save rehearsal. This will allow the remaining contract to be completed without guessing selectors or filename formats.
