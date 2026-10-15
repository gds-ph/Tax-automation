# 1601C Stage 2 profile and saved-return lookup repair

Installed 12 October 2026 in existing Stage2_Submit_1601C, preserving its 23 inputs, 2 outputs and authorization guards.

KINGBA September 2026 work order 1c66a4aa-8280-498f-ae95-758e6bbb80c2 had failed attempt d5616b85-5f44-412c-b7ed-f8e32090a0a9 with SAVED_RETURN_ROW_NOT_FOUND. The opening profile had no branch code, while the approved XML existed. Changed four TIN input actions to direct simulated field population. Replaced OCR filename/offset selection with a simulated click on the radio button identified by the exact ApprovedXmlPath, retaining lookup retries and failure handling.

Selection-only rehearsal populated all TIN segments, loaded KINGBA profile, and opened its September 2026 1601C. It stopped before validation or submission. Restored and saved the full 67-action flow; exported installed flow and verified four direct inputs, exact row selector, no OCR, no hardcoded rehearsal inputs, and preserved submission guard.

Backup: ../work/1601c-stage2-before-fix.pad.txt
Installed export: ../outputs/Stage2_Submit_1601C-installed.pad.txt
Rehearsal: ../work/1601c-stage2-rehearsal.pad.txt

The failed dashboard submission was not requeued by this repair. Parent worker remains stopped. No live submission occurred during testing.
