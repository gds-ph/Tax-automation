# 1601EQ Stage 2 saved-return selection repair

Installed 12 October 2026 in the existing Stage2_Submit_1601EQ flow (863fba08-1fda-45b7-9c56-8cb30c97e7e4).

Replaced OCR filename matching and positional click with a simulated UI Automation click on the saved-return radio button whose Id is %ApprovedXmlPath%, followed by View. Retained retries and SAVED_RETURN_ROW_NOT_FOUND failure handling. Existing file uniqueness, approved XML path, period, filename and submission authorization guards remain unchanged.

A selection-only rehearsal selected and opened APEXERY INC., 1601EQ, Q3 2026. It contained no validation, save or submission actions. Restored and saved the full 67-action flow after the rehearsal, then exported it and verified the dynamic selector, authorization guards and absence of hardcoded test values.

Backup: ../work/1601eq-stage2-before-selector-fix.pad.txt
Installed export: ../outputs/Stage2_Submit_1601EQ-installed.pad.txt
Rehearsal: ../work/1601eq-selector-rehearsal.pad.txt

No BIR submission performed. Parent worker remains stopped; the failed job requires dashboard approval before another submission attempt.
