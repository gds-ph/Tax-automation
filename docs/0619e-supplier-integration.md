# 0619E supplier preparation

Connected deployment installed on 12 October 2026 following user approval. End-to-end Stage1 verification passed for supplier and zero modes. Synthetic samples are not real filings and must not be approved or submitted.

## Installed changes

- Server backend, review/queue dashboard, and migration 0028 deployed. Preserved the existing server prepare-page layout.
- `Stage1_Prepare_0619E` updated to 101 actions; parent `eBIR_Work_Order_Agent` updated to 113 actions. Existing inputs/outputs retained.
- VM WorkerBridge and XML verifier installed; added `PREPARE_0619E_SUPPLIERS` to existing worker capabilities.
- Server backup: `/home/nodeadmin/ebir-deployment/backup-0619e-suppliers-20261012T031743Z` (source, image, database).
- VM backup: `C:\TaxAutomation\Backup-0619E-Suppliers-20261012-111809`.
- PAD originals: `work/agent-before-suppliers.pad.txt`, `work/stage1-0619e-before-suppliers.pad.txt`.
- Installed exports: `outputs/eBIR_Work_Order_Agent-suppliers.pad.txt`, `outputs/Stage1_Prepare_0619E-suppliers.pad.txt`.

## User workflow

Client → 0619E → Prepare from supplier schedule → enter/review/save a monthly worksheet → Review and prepare 0619E → confirm → queue. The existing worksheet also supports reviewed Excel import. Only the first two months of each calendar quarter are supported.

The queued work order stores an immutable copy of the rows and draft revision. Changes to the worksheet do not change an existing filing. Stale review tokens are rejected. This version supports positive withholding on original private-agent returns without prior remittance credits, amendments or penalties. ATCs and rates are preparer-reviewed; the system does not determine their tax applicability.

## Worker contract

- New preparation capability: `PREPARE_0619E_SUPPLIERS`.
- Existing `Stage1_Prepare_0619E` handles both zero and supplier totals.
- Inputs contain `SupplierSchedule` (`0619e-suppliers-v1`) and `WithholdingTotal`.
- Worker Start writes attempt-specific `suppliers.json`; Stage1 defaults to zero when this is absent.
- Stage1 selects withholding Yes and fills item 14; eBIRForms calculates items 16 and 18.
- `Test-0619EPreparedXml.ps1` checks saved identity, period, filing mode, amount, zero credits and penalties. Used before publishing and by the existing Stage2 bridge before submission.
- Existing saved XML blocks preparation; no silent overwrite.
- Non-zero work orders require manual approval of the prepared PDF. No automatic approval and no live submission during testing.

## Verification

- 34 focused Django tests passed in the server deployment image before activation.
- PowerShell syntax and XML guard tests passed under Windows PowerShell 5.1, including valid zero/non-zero returns and six mismatch cases.
- Browser verified manual supplier entry, calculation, saved revision, signed review, and queueing.
- Synthetic sample: Test Company, July 2025, two rows, total 2500.00; work order `ef8e0c49-6456-49e1-88dd-a25637c3623d`.
- Supplier sample completed automatically through the permanent parent worker: AWAITING_SUBMISSION_APPROVAL, one-page PDF, saved XML items 14/16/18 = 2500.00, withheld Yes, final flag 0.
- Zero regression sample: Test Company, August 2025, work order `75b5e365-825d-4c47-8969-68d0ab0a53a3`; AWAITING_SUBMISSION_APPROVAL, one-page PDF, XML items 14/16/18 = 0.00, withheld No, final flag 0.
- Both records have zero Stage2 approvals. No BIR submission performed. Existing queued approvals inspected before starting had submission_enabled=False.
- Worker remains running using the permanent updated parent flow. No temporary test flow was installed.
- Visual inspection found an eBIRForms print-template limitation: the long hyphenated sample email wraps into the Part II heading. Financial fields and page extent are intact. This is not fixed by the supplier integration; review PDFs before approval.
- Screenshot: `outputs/0619e-supplier-prepared.png`; rendered PDF: `outputs/0619e-supplier-pdf.png`.
