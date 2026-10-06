# 1601EQ integration

Reviewed 2 October 2026. Preparation is enabled in the live catalog and `ENABLE_1601EQ_SUBMISSION` was True on the server. These settings do not prove an installed PAD run succeeded.

The preparation and submission children are Stage1_Prepare_1601EQ and
Stage2_Submit_1601EQ, routed by PREPARE_1601EQ_ZERO and SUBMIT_1601EQ.
The parent must wait for each child and retain Poll/Start/Publish and recovery checks.

Scope: non-amended private-agent zero return, calendar year, no withholding,
remittances, credits, penalties or attachments. Nonzero data is rejected.
Existing cor_1601eq filing cards gain preparation support via migration 0015.
Existing snapshots remain immutable; create a new order after upgrading the catalog.

Contract:
- FormCode and ExpectedFormNumber: 1601EQ
- FormSelectionText: BIR Form 1601EQ
- FilingQuarter: string 1 through 4; FilingMonth and ATCCode: empty, unused
- Period: 2026Q1 (no year-end-month prefix)
- XML: <14-digit-TIN>-1601EQ-2026Q1.xml
- PDF: <ClientNameSafe>_1601EQ_2026_Q1_COMPLETE.pdf; one physical page
- Approval and screenshot requirements, execution slot, duplicate checks and archival
  remain enforced; archive only after server acknowledgement.

Stop the PAD parent, extract the worker update on that Windows machine and run:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-1601EQ.ps1

Use the Windows user that runs PAD. Installer backs up bridge scripts and config,
retains existing keys/token and never changes journals. Configure both parent routes
and all child input/output mappings before installing. Do not run old and new parents
in parallel. Use a fresh dashboard work order for integration testing; standalone
PAD test files are not automatically approved or linked to dashboard orders.

ENABLE_1601EQ_SUBMISSION defaults to 0. Enable only after the installed worker and
final submission child selectors/approval guards have been verified. Successful
open-and-validate rehearsal ends BLOCKED_NOT_APPROVED with both submission flags False.
Receipt matching and final-package generation use the existing shared pipeline;
TRRC escalation now applies to eligible tracked forms, including 1601EQ; see [receipt checks](bir-receipts.md) for recipient and delay settings.
