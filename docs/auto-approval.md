# Optional automatic approval

On the Prepare page, an authorized approver can select **Auto approve and submit after successful preparation**. It is unchecked by default and applies only to that work order and snapshot. The text records advance submission authorization; it does not claim that the approver reviewed a PDF that has not yet been generated.

The server requires both `automation_api.approve_stage2` and `workorders.view_prepared_pdf`. Successful preparation must upload a verified PDF and return the expected XML and PDF paths. Automatic approval then uses the existing Stage 2 service, including live-submission availability, current permissions, snapshot and PDF checks, and duplicate protection. The existing VM worker claims the queued submission normally.

Failed preparation, changed snapshots, revoked permissions, or other blocked approvals require manual review. The work order displays the automatic approval state and blocking reason. Existing filings and ordinary unchecked requests retain manual approval. Replaying a preparation request cannot add authorization to an existing order.

Deployment requires application code and migration `automation_api.0014_auto_submission_consent`; run `python manage.py migrate` before starting the updated web and worker services. No PAD flow change is required. This feature does not change portal access permissions or represent agency approval of automation.
