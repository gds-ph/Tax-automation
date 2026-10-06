# Receipt checks and final filing packages

Reviewed 2 October 2026 against `automation_api/receipts.py`, `gmail_receipts.py`, `finalize_receipt.py` and `workorders/client_directory.py`.

## When checks run

Receipt discovery applies to non-archived, live-enabled approvals in `SUBMITTED_WAITING_FOR_CONFIRMATION`. Preparation, approval alone and rehearsal outcomes do not trigger mail checks. Matching requires the saved XML basename (including 0619F's WB suffix), configured receipt sender, receipt subject and a message time at or after the submission attempt. Plain text and HTML receipts are supported.

The Linux `receipts` service runs `check_bir_receipts`, then waits 60 seconds before the next pass. Each filing's interval is set by `receipt_check_interval_minutes` in Settings (1?1440 minutes), defaulting to one minute. Runtime and downtime can extend actual intervals. Delayed mail never queues another submission.

## Mailbox configuration

The current dashboard Gmail settings use an address and App Password for IMAP. The page requires a superuser; saving also requires mailbox-change permission. The saved password is encrypted in the database using the application secret. Preserve that secret with backups. Environment address/password settings provide a fallback. Never paste credentials into docs or commands.

OAuth lookup support remains in the module for configurations without IMAP credentials; the earlier OAuth callback setup is not the current dashboard setup flow. IMAP receipt reads do not mark messages read.

## Missing-TRRC escalation

The implementation can send SMTP follow-up email for eligible tracked forms, including 1601EQ and 0619F; it is no longer restricted to 1601C. Delay and recipient come from Settings/environment. Review the configured recipient and delay, particularly in simulation deployments. Failures are recorded and retried; a sent timestamp prevents ordinary repeat sends. Email delivery and database recording are not an atomic transaction, so uncertain delivery needs review.

The receipt checker therefore is not strictly read-only: receipt lookup reads mail, but escalation sends email. This documentation update does not trigger any messages.

## Final package and paths

After receipt matching, the finalizer combines the return, receipt and submission screenshot. The dashboard exposes it under **Documents ? Final filing package**. Server copies are protected under `MEDIA_ROOT/final_packages`.

The office-share destination chooses the existing company `BIR` folder first, then `BIR FILING`, then `FILED RETURNS`:

```text
\\192.168.8.251\Starlight\Starlight offline\CLIENT\<Company>\BIR\2026\01 JANUARY\
\\192.168.8.251\Starlight\Starlight offline\CLIENT\<Company>\BIR\2026\02 FEBRUARY\
```

Monthly folders use the filing year/month, not today's date. Names are `01 JANUARY` through `12 DECEMBER`. Existing matching folders are reused; older files are not moved. Quarterly packages currently upload directly into BIR/FILED RETURNS. A missing configured company/root or share failure is recorded in `receipt.evidence['client_archive']`; a dashboard package alone does not prove an office-share copy succeeded. An already finalized package is not automatically archived again by the finalizer.

The submitted XML has a different VM archive; see [Submitted XML archiving](submitted-xml-archive.md). Receipt email confirmation is separate from final tax-authority validation.

## Operation

Keep one receipt service for the active database. Do not also run the older Windows scheduled task against the same deployment. Inspect last-check/error details, service logs and archive evidence when diagnosing failures. See [server deployment](docker-server.md) for service and backup commands.

Archive folder names are matched case-insensitively. BAIYI uses `BAIYI CONSTRUCTION DEVELOPMENT CORP/BIR FILING`; the older registration source folder name is not its current package destination. The explicit client folder setting overrides that older source reference.
