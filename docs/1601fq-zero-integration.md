# 1601-FQ zero filing

Status on 11 November 2026: application contract and catalog migration implemented; PAD installation and live deployment are not complete. Preparation and submission remain disabled by default. Do not advertise PREPARE_1601FQ_ZERO in a worker until its child flow and parent dispatch have been installed and tested.

## Scope and evidence

The user confirmed 1601-FQ, not the historical monthly 1601-F. The installed runtime cache contains forms/BIR-Form1601FQ.hta, marked January 2018 on both logical pages. Its createXMLFileName function builds <TIN and branch>-1601FQ-<YYYY>Q<quarter>.xml without a year-end-month prefix or WB suffix. This is code inspection evidence; a saved dummy return and rendered PDF still require verification.

The contract permits only calendar-year, original private-agent zero returns: no withholding, remittances, credits, penalties, treaty claims or attachments. No existing company receives a new filing obligation automatically. The form can be selected explicitly in company registration/setup after deployment. Official reference: https://efps.bir.gov.ph/efps-war/EFPSWeb_war/forms2018Version/1601FQ/1601fq_guidelines.html

## Implemented

- Registry definition 1601fq_zero and idempotent catalog migration 0031_form_1601fq; preparation stays disabled.
- Quarterly catalog/setup mapping, overview filter and work-order visibility.
- Zero-only preparation UI, no irrelevant ATC field and no automatic submission option.
- Preparation payload and bridge allowlist key PREPARE_1601FQ_ZERO, quarterly identity/reservation rules, and expected two-page PDF validation.
- Nonzero, unreviewed, wrong-period and unsupported data rejection. Both kinds of Stage 2 approval remain blocked; no submission route or capability was enabled.

## Verification and remaining work

Offline tests exercise catalog validation, all four quarter identities, strict zero-only values, company setup mapping, disabled-route queue protection, worker capability isolation, payload paths, one-page rejection/two-page acceptance, result publication, duplicate-period protection and submission blocking. These use synthetic data and do not contact BIR. The final targeted run passed all 68 tests, including existing 1601EQ and client-navigation regressions. Django system checks, migration drift check and git diff --check passed.

PAD was running its polling loop when inspected. The server showed no RUNNING attempt, but the parent Designer displayed Not Responding. A Stop input timed out, and a fresh window inventory confirmed the nonresponsive window. No forced termination, flow edit or new filing run was performed. This prevents a verified PAD installation in this session.

Next: restore Designer responsiveness; create Stage1_Prepare_1601FQ with form-specific controls; map its inputs/outputs in the parent; verify year/quarter, original/No withholding/Private values, validation, saved XML identity and zero values, and both print pages in order using a test client. Only after that rehearsal should the runtime capability and preparation catalog flag be enabled. A separate Stage 2 implementation and approval are required before submission.

Do not use another form's selectors or mark this integration production-ready based only on the offline API tests. No taxpayer documents, credentials or full PAD UI repositories belong in Git.
