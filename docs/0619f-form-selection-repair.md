# 0619F preparation selection repair — 10 November 2026

The latest parent-worker run failed in `Stage1_Prepare_0619F`, action 35:
the 60-second wait for `BIR Form No. 0619-F` / `Edit 2` timed out. The
preceding form-selection keystrokes and Fill-up/OK clicks were logged as
successful, but the observed main page still displayed `{Please Select}...`.
This is a preparation issue, separate from the 1601EQ resend script repair.

The old `Text 7` selector ended at a text child beneath the `formType`
combobox, and both form-selection actions sent keys to the foreground window.
The repair removes that trailing text node and targets the combobox directly.
Both actions now use `FocusAndSendKeysByControl`, with
`{Home}%FormSelectionText%{Tab}` and simulated text. PAD imported the revised
element as `Text 7 2`. All other action text is unchanged after accounting for
that element-reference rename. The flow remains 82 actions.

## Verification

- Backed up the installed flow before editing.
- Imported and copied back the repair; verified both targeted actions and the
  selector path `pane > pane > combobox`.
- Designer showed no errors; save completed and the status returned to Ready.
- No flow was run and no return submitted. End-to-end preparation remains
  unverified until the next retry.

Full exports are restricted local files, excluded from Git because they contain
embedded screenshots. Under `C:\TaxAutomation-work`:

| File | SHA-256 |
| --- | --- |
| `Stage1_Prepare_0619F.before-20261110.txt` | `099F039D7E56D0CEC7F4B3FA27C524AA3088AC0AAEB5FE4FD9E1BEB1E516ED9C` |
| `Stage1_Prepare_0619F.after-20261110.txt` | `087CC09FE85CAFDCD98BFF2D5B9DD39AF6E60D91CE0FF39BBFE8039596D7555D` |

The action-only snapshot in `pad-actions/Stage1_Prepare_0619F.actions.txt`
is for review, not standalone import: it requires the corresponding UI repository.

## Worker recovery

The server already marked the exact failed preparation attempt ABANDONED,
released its execution slot and left the test order FAILED_SYSTEM. The local
journal incorrectly remained Running. After checking that identity against the
server, backed up the journal and set it to Completed with its claim/result
cleared, following the documented recovery procedure. The failed attempt and
server audit history were retained. Closed the leftover main eBIRForms window.

The order was not automatically retried. Next: choose Retry preparation for the
failed Test Company October 2026 0619F order and start one parent worker after
reviewing the queue. Do not run the child directly. Observe that the dropdown
selects 0619F and its form opens before considering this repair fully verified.
