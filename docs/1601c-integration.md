# 1601C integration

Reviewed 2 October 2026. Code and live preparation support exist. `ENABLE_1601C_SUBMISSION` was True on the server when checked today; installed desktop behavior still requires operational verification.

The monthly preparation contract targets the PAD flows `Stage1_Prepare_1601C`
and `Stage2_Submit_1601C`. The tested preparation scenario is a private withholding
agent with no compensation, withholding, attachments, tax relief or prior-month
adjustments. Positive compensation is now supported through the separate reviewed payroll-summary path below, including zero withholding.

The preparation UI requires explicit confirmation of this scope. It stores a
month (1–12), no quarter, and sends `FilingMonth` to PAD as two-digit text.
For January 2026:

- Return period: `012026`
- XML: `<TIN1><TIN2><TIN3><TIN4>-1601Cv2018-012026.xml`
- PDF: `<ClientNameSafe>_1601C_2026_01_COMPLETE.pdf`
- Preparation key: `PREPARE_1601CV2018_ZERO`
- Submission key: `SUBMIT_1601CV2018`

The app binds approval to the prepared snapshot/PDF. Monthly duplicate checks
use TIN, branch, form, year and month, independent of accounting year end.
Archiving does not remove approval history or permit another submission of that
month. Both forms share the existing execution slot and recovery journals.

## VM parent flow installation and verification

Stop the parent agent while editing. Copy the updated `WorkerBridge.ps1`,
`Stage2Bridge.ps1`, and `Archive-SubmittedReturn.ps1` to `C:\TaxAutomation`.
Their default capabilities remain 2551Q-only, so copying them alone does not
claim monthly work.

In the parent preparation branch, route by the exact `AutomationKey`:

| Key | Child |
| --- | --- |
| `PREPARE_2551QV2018_ZERO` | Existing 2551Q preparation child |
| `PREPARE_1601CV2018_ZERO` | `Stage1_Prepare_1601C` |

Retain Poll → Start → wait for child → Publish. Reject unknown keys before Start.
Map the 1601C child inputs from the claimed job's `Inputs`, including `FilingMonth`.
Do not use the child's test defaults. Reuse the current preparation output variable
mapping and result JSON. `FilingQuarter` and `ATCCode` are empty for 1601C and unused
in its enabled actions. `YearEndMonth` is supplied for compatibility but must not
be used to build its monthly filename.

Only after the preparation branch is wired, add this property to the VM's existing
worker configuration, preserving its API URL/token and other settings:

```json
"PreparationAutomationKeys": ["PREPARE_2551QV2018_ZERO", "PREPARE_1601CV2018_ZERO"]
```

Verify a newly queued preparation through the app, including PDF page order, TIN,
month/year, and uploaded PDF/XML paths. Earlier standalone PAD test outputs are
not automatically imported into an approved work order.

In the parent Stage 2 branch, route `SUBMIT_1601CV2018` to `Stage2_Submit_1601C`
and retain the existing `SUBMIT_2551QV2018` branch. Map `FilingMonth` from the
job inputs. Preserve the established mappings:

| Child input | Job input |
| --- | --- |
| `ExpectedSavedReturnName` | `ApprovedSavedReturnName` |
| `ExpectedReturnPeriod` | `ApprovedReturnPeriod` |
| Other child inputs | Same-named entry in `Inputs` |

Keep output mappings `SubmissionStatus` → `Stage2SubmissionStatus` and
`SuccessScreenshotPathOutput` → `Stage2ScreenshotPath`. Report with the claimed
AttemptId. Never construct an approval or substitute a different XML by hand.

After reviewing the live-dialog selectors and completing parent routing, the
worker can advertise:

```json
"Stage2AutomationKeys": ["REVALIDATE_2551QV2018", "SUBMIT_2551QV2018", "SUBMIT_1601CV2018"]
```

The server setting `ENABLE_1601C_SUBMISSION` defaults to `0`. Live approval is
blocked and hidden until explicitly enabled with `1` in the server environment
and the server restarted. The code default is disabled; the current server setting was verified enabled on 2 October 2026.
There is no queued 1601C rehearsal key; standalone open-and-validate tests keep
both PAD submission flags False and finish `BLOCKED_NOT_APPROVED`.

Live success requires the existing screenshot upload and server acknowledgement
before automatic XML archiving. The shared helper accepts both live form keys.
The post-submission 1601C dialogs have only had their selectors adapted; their
real behavior is not yet verified. Missing evidence must never trigger an
automatic resubmission.


## Reviewed payroll summary (12 October 2026)

From a client's 1601C preparation card, select **Prepare from payroll summary**. Enter
monthly totals from completed payroll, preview the reconciliation, then confirm
the reviewed figures to queue preparation. This is direct entry; Excel import
and employee-by-employee tax computation are not included.

The first version accepts original private-employer returns only, with no
adjustments, remittance credits, relief, attachments, or penalties. It maps
items 14–20, 23 and 25 and reconciles items 21, 22, 24 and 36. Compensation must
be positive; withholding may be zero. Use the existing zero-filing route for
no compensation. Other exempt compensation needs a description of at most
25 characters, matching the eBIRForms field.

The signed review expires after 30 minutes and is bound to the user, filing
profile and source versions. The queue stores immutable amounts in the work
order snapshot. It requires manual prepared-PDF approval; advance automatic
submission approval is disabled for payroll returns.

- Preparation capability: `PREPARE_1601CV2018_PAYROLL`
- Parent route: same `Stage1_Prepare_1601C` child and existing inputs/outputs
- Start bridge writes reviewed values to `OutputFolder\payroll.json`
- Child uses the file only when present; existing zero jobs keep their route
- Publish and Stage2 Start run `Test-1601CPayrollXml.ps1` to compare saved identity,
  period, scope and every amount against the snapshot before continuing
- Existing XML for the period blocks preparation; it is never overwritten
- Submission still uses `SUBMIT_1601CV2018` after approval

Install `WorkerBridge.ps1`, `Stage2Bridge.ps1` and `Test-1601CPayrollXml.ps1`
together. Add the payroll preparation capability only after the PAD child and
parent route are installed. Recovery can retire Running or Publishing journals
only after the server confirms an operator-abandoned matching preparation;
the old journal is backed up. A mismatch must be investigated, never bypassed
by substituting success or approving the old PDF.


### PAD maintenance notes

Use PAD's `{Control}({End})` syntax for Ctrl+End. The old `^{End}` text
inserted a literal caret into the focused field and could replace a payroll
description. Validate, Save and Print use simulated clicks with stable IDs.
Leave the existing PDF merge input ordering in place: on this installed PAD
version it produced logical page 1 followed by page 2; verify the resulting
PDF rather than inferring order from the action's text representation.


### Verification on the deployment VM

On 12 October 2026, Test Company preparations for November 2025 (100,000
compensation, 7,500 withholding) and October 2025 (100,000 compensation, zero
withholding, 1,000 other exemption with a description) reached awaiting
submission approval. Saved identity, period, scope, description and amounts
matched the reviewed snapshots; both rendered PDFs had two complete pages in
logical order. Neither sample was approved or submitted to BIR.

Fifteen focused backend tests passed locally and in the server image. XML guard
checks rejected changed TIN, month and withheld tax. The worker retries only
explicit `write_conflict` result responses, at most twice, using the same
attempt/body; permanent result failures stop without retry. Worker scripts
passed PowerShell parsing and bounded retry checks.
