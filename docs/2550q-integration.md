# 2550Qv2024 preparation

Updated 15 October 2026: taxpayer classification is selectable and carried into PAD; the saved XML is checked against that selection. The later full-screen Stage 2 export captures the application and success dialog rather than only message text. See the [current guide](current-system-guide.md) and [PAD inventory](pad-release-inventory.md). Original deployment/test notes below retain their dates.


The supplied parent routes PREPARE_2550QV2024_ZERO to Stage1_Prepare_2550Q. This integration prepares only calendar-year, original, full-quarter, Micro, Small, Medium or Large zero returns without tax relief, amounts, credits or adjustments. The preparation page requires explicit confirmation of that scope. Fiscal years and non-zero returns are rejected.

Existing COR 2550Q cards are upgraded in place. Historical work-order snapshots remain unchanged. Stage 2 uses SUBMIT_2550QV2024. Live approval and auto-approval require ENABLE_2550Q_SUBMISSION=1; it defaults off until the dynamic saved-return selector is confirmed.

PAD receives FormCode=2550Qv2024, ExpectedFormNumber=2550Qv2024, the full supplied dropdown text, quarter/year, YearEndMonth=12, blank FilingMonth and ATCCode. XML: TIN-2550Qv2024-12YYYYQn.xml. PDF: ClientNameSafe_2550Qv2024_YYYY_Qn_COMPLETE.pdf, exactly two physical pages.

Deploy the server changes and migration workorders.0024_form_2550qv2024 first. On the VM, stop the parent PAD flow, extract the worker update, and run Install-2550Q.cmd as the same Windows user as PAD. It backs up and replaces WorkerBridge.ps1, then adds the preparation capability to worker.json while preserving existing configuration and journals. Restart one parent flow. Do not install during an active attempt.

The bridge maps the supplied flow's PREPARATION_BLOCKED_EXISTING_OUTPUT and PREPARATION_FAILED_INVALID_QUARTER results to FAILED_BUSINESS and omits output paths on unsuccessful 2550Q preparation. The original PAD status remains in the journal. Existing files are not uploaded as new results. A blocked result needs operator review; do not delete an existing return to force a retry.

Verification uses synthetic PDFs and mocked worker API calls. A desktop run remains necessary to confirm UI selectors and print layout in the actual VM; no real filing is executed by the tests.

## Stage 2

The supplied Stage2_Submit_2550Q flow checks ApprovedReturnPeriod=YYYYQn and constructs its XML basename by prefixing YearEndMonth=12. The Stage 2 payload follows that convention; Stage 1 still uses 12YYYYQn. Both identify the same XML. A successful result requires the screenshot upload before result publication, then the existing receipt discovery and archive workflows handle the return.

Stop the parent flow and run Install-2550Q-Stage2.cmd on the PAD VM. It preserves credentials and journals and installs all three bridge/archive scripts with the new preparation and submission capabilities. The parent must route SUBMIT_2550QV2024 to Stage2_Submit_2550Q (flow ID d86cc279-77e5-41fb-a089-55ee0404ecc8).

The pasted Stage 2 export contains no ControlRepository selector data. The operator confirmed the saved flow selects radiobutton[Id="%ApprovedXmlPath%"] dynamically and that it passed a local test. The flow verifies the expected basename and full XML path before selection. Live submission was enabled on 10 October 2026 after this confirmation; deployments elsewhere must verify the installed flow before enabling it. No desktop submission is performed during integration tests.
