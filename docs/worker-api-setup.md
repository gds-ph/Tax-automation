# Stage 1 worker API and Hyper-V PAD setup

Reviewed 2 October 2026. The API, preparation transfers and Stage 2 integration are implemented. The active server is `https://192.168.8.200:8443`; the Windows VM remains a separate machine. Localhost inside the VM is not the server. Use [Linux deployment](docker-server.md) for current TLS and endpoint setup; the older Windows-host HTTPS guide is historical.

The parent PAD flow is installed and maintained by the operator. Code deployment does not launch PAD or prove its selectors work. Keep dummy rehearsals out of live submission.

## Prototype policy

- Supported keys: `PREPARE_2551QV2018_ZERO`, `PREPARE_1601CV2018_ZERO`, `PREPARE_1601EQ_ZERO`, `PREPARE_0619F_ZERO`. The worker must advertise only installed routes.
- One global execution slot; oldest eligible task first.
- Lease: 30 minutes. Poll interval: 15 seconds. No automatic retry/reassignment
  after expiry: an expired lease does not prove desktop automation stopped.
- Stale/inactive configuration is not claimed. An attempt uses its immutable
  snapshot even if the client changes after the claim.
- A return awaiting review reserves its XML filename against another preparation.
- Failed system/PDF/XML preparation can use **Retry preparation** after the previous attempt finishes or is released. The same order/snapshot and attempt history are retained. Active, successful, archived, approved and file-bearing orders require separate review. Source changes can block retry. See [recovery](worker-preparation-recovery.md).

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
token hash. For a new worker, supply the verified server endpoint using `--base-url`. Preserve an existing worker configuration instead of provisioning a duplicate. The default URL is for a loopback health check only:

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
Stage 1 and waits for completion. The integrated parent also polls Stage 2 when no preparation work is available; see [Stage 2 setup](stage2-connection.md). Run only
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

3. Validate `Job['AutomationKey']` against the installed routes and dispatch to the matching child. Never route an unknown form to the 2551Q flow. Consult the 1601C, 1601EQ and 0619F integration guides for their exact keys and inputs.

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

The table is the original 2551Q input contract. Monthly flows also use `FilingMonth`; unused quarter/ATC values must not be substituted into monthly filenames. Inputs are text. OutputFolder is an attempt-specific subfolder under
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
| GET | `/api/agent/health/` | Health, API version and poll interval; do not treat its legacy submission field as a per-form capability list |
| POST | `/api/agent/preparation/claim/` | JSON `request_id` UUID and installed preparation `automation_keys`; claim or 204 |
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
as an unencrypted PDF with the form-specific page count: two for 2551Q/1601C and one for 1601EQ/0619F. Obvious embedded actions/attachments are rejected.
Storage filenames are generated by Django. Upload alone leaves processing status.
Completion verifies the stored hash again and records the exact XML result before
entering Awaiting submission approval. XML metadata is a worker report, not proof
that Django inspected the VM file or that its data equals the PDF. PDF validation
is not malware scanning; downloads are authenticated attachments, not public URLs.

## Operator recovery and review

Stop both PAD flows before releasing an interrupted preparation. An authorized operator uses **Release interrupted run** in the filing's Overview. The endpoint binds the attempt to that filing, checks its version and records the release. Merely expired leases are not automatically released.

Install the one-time dashboard recovery bridge from `/worker/recovery-update/` on the VM with both flows stopped. Extract the ZIP and double-click `Install-DashboardRecovery.cmd`. It updates only the bridge and preserves configuration/journals. After dashboard release, restart one parent worker; a matching Running preparation journal is backed up and cleared through the authenticated recovery check. Publishing and Stage 2 journals are excluded.

`POST /api/agent/preparation/{AttemptId}/recovery/` accepts `lease_token`, `work_order_id` and `automation_key`. It is read-only on the server and authorizes local cleanup only for the exact owned abandoned preparation attempt. It never releases an active attempt itself.

Regular preparers may choose **Retry preparation** for eligible failed orders after recovery. Worker release/download actions require operator permissions. Protected PDF access and Stage 2 approval use their own permissions. Follow [the recovery guide](worker-preparation-recovery.md) for manual fallback and [Stage 2](stage2-connection.md) for submission uncertainty.

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
