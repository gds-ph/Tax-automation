# Stage 1 worker API and Hyper-V PAD setup

The Django side and Windows transfer helper are implemented and tested locally.
Your existing `Tax-Filing`, `Tax-Filing - Copy`, and `Stage2_Open_Approved_Return`
flows have not been edited. No PAD flow or eBIRForms execution has been performed
by these tests. BIR Submit / Final Copy remains disabled.

## Current connection boundary

Django still listens only on `127.0.0.1:8001`. Inside the VM, `127.0.0.1` refers
to the VM itself, not the dashboard host. The helper requires HTTPS for a remote
connection; HTTP is accepted only for loopback tests. A Caddy HTTPS proxy now
listens on `192.168.8.148:8443` and accepts worker API paths only from the VM
at `192.168.14.135`. The host firewall rule still needs Administrator execution;
VM certificate trust and end-to-end connectivity remain pending.
See [the concrete HTTPS setup](worker-https.md). Hyper-V networking and Django
ALLOWED_HOSTS remain unchanged.

## Prototype policy

- Only `PREPARE_2551QV2018_ZERO` is supported.
- One global execution slot; oldest eligible task first.
- Lease: 30 minutes. Poll interval: 15 seconds. No automatic retry/reassignment
  after expiry: an expired lease does not prove desktop automation stopped.
- Stale/inactive configuration is not claimed. An attempt uses its immutable
  snapshot even if the client changes after the claim.
- A return awaiting review reserves its XML filename against another preparation.
- Completed/failed work orders cannot be edited into a fresh execution. A retry
  needs deliberate review and a new work order, with any XML reservation resolved.

Constants are in `automation_api/worker_policy.py`. Confirm actual Stage 1
runtime before the VM test. Start renews the lease; Renew is also available.
There is no background heartbeat while a synchronous child flow runs. If Stage 1
can exceed 30 minutes, adjust the reviewed lease policy or implement renewal
before testing. An expired lease cannot be revived.

## Provision on the dashboard host

Use the existing authorized superuser's username:

```powershell
.\.venv\Scripts\python.exe manage.py provision_worker --actor YOUR_USERNAME --name HYPERV-EBIR --token-file .\secrets\hyperv-worker.json
```

The command writes a new ignored credential file without printing the token.
It refuses to overwrite a file or reuse an agent name. Django stores only the
token hash. No real worker credential was issued during development. Its default
URL is for a dashboard-host loopback health check only:

```powershell
$workerConfig = Get-Content -LiteralPath .\secrets\hyperv-worker.json -Raw | ConvertFrom-Json
Invoke-RestMethod -Uri ($workerConfig.ApiBaseUrl + '/api/agent/health/') -Headers @{Authorization = 'Bearer ' + $workerConfig.Token}
```

Do not call Claim on the host just to test connectivity: it would claim a queued
local order. Automated tests use an isolated database and files.

After configuring the private HTTPS endpoint, set `ApiBaseUrl` to that verified
address. Securely copy the credential into the VM, under the account running PAD:
`%LOCALAPPDATA%\TaxAutomationWorker\worker.json`. Copy `worker/WorkerBridge.ps1`
to `C:\TaxAutomation\WorkerBridge.ps1` in the VM. Its journal and result file
stay beside the per-user credential. Keep tokens out of chat, URLs, PAD source,
and Git. Do not share an agent credential or journal between VMs.

## New PAD wrapper: eBIR_Work_Order_Agent

Start the wrapper manually in the VM's interactive session. It calls the existing
Stage 1 and waits for completion. It does not call either Stage 2 flow. Run only
one wrapper instance. A local mutex serializes helper operations; Django also
prevents multiple active attempts.

1. Add **Run PowerShell script** for Poll, with this fixed trusted helper path:

   ```powershell
   & ([scriptblock]::Create([IO.File]::ReadAllText('C:\TaxAutomation\WorkerBridge.ps1'))) -Action Poll
   ```

   Capture output as `WorkerResponse`; use **Convert JSON to custom object**
   to create `Job`. Never interpolate taxpayer values into PowerShell source.

2. If `RecoveryRequired` is True, stop and inspect the journal; do not rerun
   Tax-Filing. If `HasTask` is False, wait 15 seconds and poll again. On helper
   errors, stop and inspect server/journal rather than using default inputs.

3. Require `Job['AutomationKey']` to equal `PREPARE_2551QV2018_ZERO`.
   Never route an unknown form to the 2551Q flow.

4. Run the same snippet with `-Action Start`; parse its result and require
   `Started = True`. It renews the lease, creates the output directory and
   journals Running before PAD execution. A later Poll will refuse to rerun it.

5. Add **Run desktop flow**, select **Tax-Filing**, and keep **Wait for flow to
   complete** enabled. Map all inputs below. The child runs in the same Windows
   session; its outputs are available after it returns. A queued Q2 must override
   the test/default Q3 value.

| Tax-Filing input | PAD value (classic variable syntax) |
| --- | --- |
| TIN1 | `%Job['Inputs']['TIN1']%` |
| TIN2 | `%Job['Inputs']['TIN2']%` |
| TIN3 | `%Job['Inputs']['TIN3']%` |
| TIN4 | `%Job['Inputs']['TIN4']%` |
| RDOCode | `%Job['Inputs']['RDOCode']%` |
| RegisteredName | `%Job['Inputs']['RegisteredName']%` |
| RegisteredAddress | `%Job['Inputs']['RegisteredAddress']%` |
| ZipCode | `%Job['Inputs']['ZipCode']%` |
| TelephoneNumber | `%Job['Inputs']['TelephoneNumber']%` |
| EmailAddress | `%Job['Inputs']['EmailAddress']%` |
| LineOfBusiness | `%Job['Inputs']['LineOfBusiness']%` |
| FormSelectionText | `%Job['Inputs']['FormSelectionText']%` |
| FormCode | `%Job['Inputs']['FormCode']%` |
| ExpectedFormNumber | `%Job['Inputs']['ExpectedFormNumber']%` |
| FilingYear | `%Job['Inputs']['FilingYear']%` |
| FilingQuarter | `%Job['Inputs']['FilingQuarter']%` |
| YearEndMonth | `%Job['Inputs']['YearEndMonth']%` |
| ATCCode | `%Job['Inputs']['ATCCode']%` |
| ClientNameSafe | `%Job['Inputs']['ClientNameSafe']%` |
| OutputFolder | `%Job['Inputs']['OutputFolder']%` |

All 20 inputs are text. OutputFolder is an attempt-specific subfolder under
`C:\TaxAutomation\Working`, created by Start to isolate PDFs. XML stays under
`C:\eBIRForms\savefile`, with the exact expected filename. Django never opens
these VM paths.

6. Build a custom object with these properties, convert it to JSON, and write
   UTF-8 text (overwrite) to `%LOCALAPPDATA%\TaxAutomationWorker\result.json`:

   | Property | Value |
   | --- | --- |
   | AttemptId | `Job['AttemptId']` |
   | PreparationStatusOutput | Stage 1 `PreparationStatusOutput` |
   | PreparedPdfPath | Stage 1 `PreparedPdfPath` |
   | SavedXmlPath | Stage 1 `SavedXmlPath` |

   Retrieve LOCALAPPDATA using PAD's environment-variable action first. Build
   the object with PAD's object/JSON actions, not string concatenation, to handle
   quotes and Windows paths. A supported failure uses its status and blank paths.
   If the child throws or might still be running, stop for operator review rather
   than reporting it finished and releasing the slot.

7. Run the fixed snippet with `-Action Publish`. The helper checks AttemptId,
   exact expected paths and existence of both VM files; hashes/uploads the PDF
   and reports the result. It never uploads XML. After accepted status, wait
   15 seconds and return to Poll.

If reporting fails after Stage 1 completes, retry **Publish only** while the
lease is live. Publishing journals the outputs before transfer. Identical PDF
and final-result retries are idempotent; changed results are rejected. Do not
rerun preparation to recover a lost upload/response. Preserve the journal after
a crash; deleting it is not a recovery procedure.

## HTTP contract

All routes require an Authorization Bearer token. Browser sessions do not grant
worker API access. Responses are JSON and no-store; empty queue/current is 204.

| Method | Route | Request / response |
| --- | --- | --- |
| GET | `/api/agent/health/` | Health, API version, poll interval, submission disabled |
| POST | `/api/agent/preparation/claim/` | JSON `request_id` UUID and `automation_keys: ["PREPARE_2551QV2018_ZERO"]`; claim or 204 |
| GET | `/api/agent/preparation/current/` | Diagnostic active attempt; no inputs or lease token; never a rerun instruction |
| POST | `/api/agent/preparation/{AttemptId}/renew/` | JSON `lease_token`; extends a live owned lease |
| PUT | `/api/agent/preparation/{AttemptId}/pdf/` | Raw application/pdf body; X-Lease-Token and lowercase X-PDF-SHA256 headers |
| POST | `/api/agent/preparation/{AttemptId}/result/` | JSON lease_token plus three Stage 1 output fields |

Claims include AttemptId, WorkOrderId, State, Status, AutomationKey, LeaseToken,
LeaseExpiresAt, SnapshotSha256, Inputs, ExpectedReturnPeriod,
ExpectedSavedReturnName, ExpectedXmlPath, ExpectedPdfPath, and relative
PdfUploadUrl, ResultUrl and RenewUrl. Completed retries return state without
Inputs. The helper omits bearer/lease tokens from its PAD-facing output.

Errors: 400 invalid content, 401 invalid/disabled token, 403 wrong lease, 404
attempt not owned/found, 409 busy/expired/conflicting result/write contention,
413 size limit, 415 wrong content type. Preserve request IDs across uncertain
delivery; never change the UUID merely to retry a claim. Unexpected exceptions
return a sanitized 500 response even under local DEBUG.

PDF uploads are limited to 25 MiB, streamed in bounded chunks, hashed and parsed
as an unencrypted two-page PDF. Obvious embedded actions/attachments are rejected.
Storage filenames are generated by Django. Upload alone leaves processing status.
Completion verifies the stored hash again and records the exact XML result before
entering Awaiting submission approval. XML metadata is a worker report, not proof
that Django inspected the VM file or that its data equals the PDF. PDF validation
is not malware scanning; downloads are authenticated attachments, not public URLs.

## Operator recovery and review

After confirming the PAD child has actually stopped, use its attempt ID and the
current work-order version from the admin/detail pages:

```powershell
.\.venv\Scripts\python.exe manage.py stop_preparation --actor YOUR_USERNAME --attempt ATTEMPT_UUID --expected-version CURRENT_VERSION --confirm-stopped
```

This audits the operator, marks the attempt abandoned and work order failed, and
releases the execution slot. It never requeues. It requires agent-change and
work-order-change permissions. Expired worker leases cannot revive the attempt.

Successful reporting exposes a protected PDF download to Preparer, Approver and
Administrator via a separate permission. The hash is verified on download.
Approval buttons, Stage 2 leasing and submission endpoints remain absent.

## Official action references

Microsoft documents flow input/output mapping and completion behavior in
[Run desktop flow](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/runflow).
[HTTP actions](https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/web)
are an alternative to the helper's requests; the supplied helper additionally
handles raw PDF transfer and durable journaling.
[Django file handling](https://docs.djangoproject.com/en/5.2/topics/http/file-uploads/)
and [pypdf PdfReader](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html)
inform protected upload validation. No paid cloud trigger or unattended-execution
licensing claim is made by this locally started wrapper setup.
