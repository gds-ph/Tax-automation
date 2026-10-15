# 1601EQ non-zero preparation

Saved QuarterlyWithholdingDraft revisions queue immutable `1601eq-suppliers-v1` schedules through `quarterly-prepare`. The view checks actor, source versions, draft version and a 30-minute signed review. Repeated requests use the same request UUID. No advance submission authorization is created.

`PREPARE_1601EQ_SUPPLIERS` routes to Stage1_Prepare_1601EQ. WorkerBridge writes quarterly.json with ATC groups sorted by the installed eBIRForms 7.9.6.1 private-agent ATC picker order. The PAD child selects ATCs, enters bases, remittances and penalties, then validates, saves and prints. Test-1601EQPreparedXml verifies identity, scope, each group and all totals before publication and before Stage 2.

Supported: calendar-year original private-agent returns, at most six ATCs, positive withholding, nonnegative tax due, reviewed payment amounts and user-entered penalties. Consolidate each ATC base and round its tax once for PAD, retaining transaction-level amounts unchanged. The preparation review discloses per-ATC and net rounding adjustments; remittances and penalties remain unchanged. Over-remittance is checked against consolidated totals. Amended credits, prior-quarter carryover, refund disposition and QAP export are separate. No actual BIR submission was used for integration testing.

PAD exports are under the workspace outputs directory. Back up installed flows before replacing actions. Install WorkerBridge.ps1, Stage2Bridge.ps1, Test-1601EQPreparedXml.ps1 and 1601eq-atc-controls.json together, then add PREPARE_1601EQ_SUPPLIERS to the existing worker preparation capabilities without changing credentials or journals.

Live verification (2026-10-14): Test Company Q3 2026 saved revision 1 completed through the installed PAD worker. Work order 8391088c-b6f9-477c-b090-b8792d77465f reached AWAITING_SUBMISSION_APPROVAL; attempt f8c55b14-d069-4cb0-8a50-354338828abf produced a verified XML and one-page PDF. Confirmed WC120/WC158, total withholding 228677.44, remittances 81188.66 and amount due 147488.78. No BIR submission performed.

ATC selection uses keyboard navigation from the opened ATC link (Tab to first checkbox, tab to each sorted index, Space to select, then Enter on OK). This avoids unreliable offscreen checkbox selectors in the legacy HTA. The XML guard rejects any selection or amount mismatch before publishing.

Recovery 2026-10-14: consolidated group rounding mirrors installed eBIRForms 7.9.6.1 binary64 base * rate / 100 and floor(value * 100 + 0.50000000001). Regression: 7751429 at 0.5 percent produces 38757.14. Attempt 824c7107-e16e-4ae2-a909-f489fcdb3f38 recovered by checking the unchanged immutable schedule, backing up its journal, refreshing only server-derived QuarterlyTotals and retrying Publish. Existing XML passed exact validation; existing PDF was visually checked. No rerun or BIR submission.
