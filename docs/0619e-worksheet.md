# 0619-E monthly worksheet

**Current status, 15 October 2026:** this worksheet is connected to PAD through saved-revision review and queueing. It also supports Excel clipboard paste. See [current workflow](current-system-guide.md) and [supplier integration](0619e-supplier-integration.md). The draft-only delivery notes below are historical.


Local draft functionality; no PAD route or submission is enabled by this change.
Open a client and choose **Open 0619-E worksheet**. The preparer selects a completed
month, enters transactions or uploads one monthly Excel schedule, previews the
calculation, and explicitly saves the reviewed draft. Saved lists replace the
month's current list; prior revisions retain rows, totals, actor, time and client
snapshot. A stale preview cannot overwrite a newer revision. Preview tokens expire
after 30 minutes and are bound to the user, client, client version and period.

The same office-wide view/add/change work-order permissions protect this worksheet.
No records are inserted in the worker work-order queue. A worksheet is neither a
filed return nor a remittance/payment receipt. This first version supports original
transaction-based drafts, without amendments, credits or penalties.

## Import contract

`.xlsx` only, up to 5 MB / 30 MB expanded and 500 transactions. Choose one visible
monthly schedule, not the combined quarterly sheet. The supplied workbook's
`(07)Schedule` and `(8)Schedule` layouts are supported. Its A3 date is checked against
the selected period. The downloadable `Transactions` template has these columns:

Payee, TIN, ATC Code, Tax Base, Tax Rate, Withholding Tax, Particulars, Year, Month.

Excel rates use percentage cells (2% = 0.02); manual entry uses 2 for 2%. TINs are
text and preserve leading zeros. Optional Year/Month cells must match the selected
period when present. Formula cells are never executed: Excel must recalculate and
save before import so cached results are available. The preview requires review of
cached amounts against invoices. Withholding is recalculated with decimal arithmetic
and ROUND_HALF_UP to centavos per transaction; supplied tax must match. Rates and
ATC applicability are reviewed inputs, not automatically inferred from descriptions.
No adjustments are silently accepted. Maximum manual editing size is 100 rows.

0619-E is for the first two months of a calendar quarter, per the
[BIR guidelines](https://efps.bir.gov.ph/efps-war/EFPSWeb_war/forms2018Version/0619E/0619e_guidelines.html).
The form-level remittance amount is the sum of transaction withholding. The schedule
retains payee ATCs for review and future 1601-EQ consolidation; these are distinct
from form-level remittance ATCs. No payment is inferred from a worksheet total.

## Remaining Stage 1 integration

Build and verify `Stage1_Prepare_0619E` in the Windows PAD VM before registering an
executable route. Verify the actual eBIRForms selection label, saved-return naming,
taxpayer type, month/year, taxes-withheld choice and remittance amount controls.
The worker must receive an immutable approved draft revision and exact decimal
amount, validate the saved XML against that revision, and return a complete review
PDF through the existing protected artifact pipeline. Keep submission out of Stage 1.
The existing zero-only work-order constraint must be migrated deliberately when
nonzero preparation is integrated; never satisfy it by falsely marking a nonzero
return as zero. No live server deployment or worker modification is included here.
