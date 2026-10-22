# PAD release inventory

Recorded 15 October 2026. These are local exports from the preceding implementation work, not a fresh export of the running PAD installation. Compare the installed flow before restoring. The source repository includes PowerShell bridges, XML validators and the ATC control map; it does not contain complete importable PAD flows.

Exports are held in `../outputs/` relative to the repository on the development VM. Back up that directory in restricted operational storage. Raw exports can contain embedded screenshots and taxpayer data, so they are deliberately excluded from Git. A Git clone alone cannot rebuild the entire Windows automation.

| Local export | Role | Prior verification | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `eBIR_Work_Order_Agent-quarterly.pad.txt` | Parent dispatcher including quarterly preparation | Installed in prior session; 113 actions | 26465 | `bbdc71c6271ad3ea313f109e9e12142660e9178bf8986c6c3bd8e145003353b0` |
| `Stage1_Prepare_1601EQ-suppliers.pad.txt` | Quarterly supplier preparation | Installed; 162 actions; preparation observed | 1963027 | `caeea917760c3422c3957a951fb93dc019d5487597a84f03a14a37186f9fb553` |
| `Stage1_Prepare_0619E-suppliers.pad.txt` | Monthly zero/supplier preparation | Installed; 101 actions; preparation observed | 330162 | `032b34c2dbdb19ca775f5abf360ff1ded752cc7b5b1c49b3c37f3cf3819c9079` |
| `Stage1_Prepare_1601C-input-fixed.pad.txt` | Payroll and zero preparation; TIN input recovery | Latest input repair; 162 actions | 3086429 | `3407934b2b1c9375abcb8e6b075c6b002959776ddd2a7f4df976bd8c956e95c4` |
| `Stage2_Submit_1601C-installed.pad.txt` | 1601C saved-return selection | Installed selector repair | 1289031 | `ef1434d5d87ee6b91e1670fe39b9bb994c66d3e5a479ee7814f03c22b2fde47e` |
| `Stage2_Submit_1601EQ-installed.pad.txt` | 1601EQ approved XML lookup | Installed; 67 actions | 1261251 | `9e66e47968f67f87b302bc11d921239dd26461998a56c9ef1fb6d9663a3d82a7` |
| `Stage1_Prepare_2550Q-classification-click.pad.txt` | VAT zero preparation with classification | Latest classification repair | 1264487 | `f9a124f1526da653136d79d6e0bf16a339bd7d501a4faa9e639289c95d114b29` |
| `Stage2_Submit_2550Q-full-screen.pad.txt` | VAT submission evidence capture | Full-screen capture change | 201811 | `2f451b89489b53b5392d911861eb6f0478f37f6549e8387b3c18708bf7609faa` |
| `Stage2_Submit_0619E.draft.pad.txt` | 0619E submission candidate | Draft export; installation not established by this inventory | 138935 | `4b3a129c568319489b1a9452ab2769564be9e9647b7773e00c6eb86d1215e8ce` |

## Restore and update

0619E screenshot audit on 19 October 2026: a fresh installed export confirmed
dialog-only capture. Replaced only that capture with a full-screen PNG at the
same `SuccessScreenshotPath`. PAD reported Saved (77 actions, 23 inputs, 2
outputs); the copied-back actions matched the repaired export. Backup:
`../outputs/Stage2_Submit_0619E-audit-20261019.pad.txt`. Installed replacement:
`../outputs/Stage2_Submit_0619E-full-screen-20261019.pad.txt` (559,865 bytes,
SHA-256 `a8afe626a6dad00f76f70e23c6bdc3da64f3455cdcadebf77cbff7236b8599fc`).
No filing was submitted for testing. Existing evidence was preserved.
Fresh installed exports for 0619F, 1600VT, 1601C, 1601EQ and 2551Q all use
`Workstation.TakeScreenshot.TakeScreenshotAndSaveToFile` at
`SuccessScreenshotPath` and required no change. They are stored as
`../outputs/Stage2_Submit_<form>-audit-20261019.pad.txt`.
Together with the verified 2550Q repair below, all seven dispatcher submission
flows now use full-screen capture. This verifies installed action configuration,
not a new live submission for each form.

2550Q submission evidence repair on 19 October 2026: the installed
`Stage2_Submit_2550Q` still captured only the success-message text UI element.
Replaced that single action with a full-screen PNG capture to the existing
`SuccessScreenshotPath`, preserving all other actions, selectors and output
contracts. PAD reported Saved with 81 actions, 23 inputs and 2 outputs. A fresh
clipboard export matched the repaired export exactly (ignoring surrounding
whitespace). No live submission was run for this check; verify the image on the
next separately approved submission. Existing cropped evidence is unchanged.

The original backup is `../outputs/Stage2_Submit_2550Q-before-20261019.pad.txt`.
The verified installed export is
`../outputs/Stage2_Submit_2550Q-installed-20261019.pad.txt` (532,467 bytes,
SHA-256 `d123b72fa3567b6951b1724c67cbeff7edb898986d553b6493ab0d5a7d9e4d3e`).
This supersedes the older full-screen candidate listed above for this repair;
that older candidate did not establish what was installed on 19 October.

2551Q repair on 15 October 2026: the installed `Tax-Filing - Copy` child flow
timed out with selectors bound to an old temporary HTA folder. Five selector
attributes were changed to ignore that temporary path, retaining control IDs,
window names and the existing 123 actions. The original export is
`../outputs/Tax-Filing-Copy-before-20261015.pad.txt`; the repaired export is
`../outputs/Tax-Filing-Copy-stable-selectors.pad.txt` (2,319,039 bytes, SHA-256
`d2b16226fa2feca13b275c733365547db117f43ced617c9dc9263854563184d3`).
Action text was verified unchanged. Retried preparation attempt
`b94b34d9-fc9a-4323-abcd-fb63415daac0` succeeded and work order
`203f6458-eae8-4f8c-930f-1521c99f1063` reached awaiting submission approval
with its XML and merged two-page PDF. The interrupted attempt was released through
the audited recovery service before retrying.

Fresh 1600VT exports from the 15 October enhancement:

| Local export | Role | Verification | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `Stage1_Prepare_1600VT-before-20261015.pad.txt` | Installed flow before enhancement | Backup; 85 actions | 1794569 | `537076facc330e17b31de3198e7343feb2f6fe22d2b6f448a54b0a3111a0fc16` |
| `Stage1_Prepare_1600VT-enhanced.pad.txt` | Enhanced zero preparation | Installed; 109 actions; test PDF/XML published for approval | 1434829 | `c2f337f713281ea902cc0c00a770bb8a6e3b797a9c5cbf7a60bca8741750aa11` |

The enhanced flow requires the matching bridge and `Test-1600VTPreparedXml.ps1`.
See [1600VT preparation](1600vt-integration.md) for test scope and recovery notes.

1. Back up the installed parent and child flows, local configuration and journals in restricted storage.
2. Select the export for the intended form and compare its checksum to this inventory. Older similarly named files are historical candidates, not automatic fallbacks.
3. Install the matching repository bridges and validators, then import or paste the reviewed PAD flow in the desktop editor.
4. Verify child-flow names, input variables, installed eBIRForms version, UI selectors and local paths. Preserve all existing worker capabilities when adding a new capability.
5. Test with a designated test client through preparation and PDF/XML verification. Keep submission separately approved; preparation success is not submission verification.
6. Record the new export, checksum and actual test outcome whenever PAD is edited.

See [system guide](current-system-guide.md) for worker contracts and recovery, and [documentation index](README.md) for form-specific setup.

### 21 October 2026: VAT PDF-save recovery

The installed 2550Q preparation timed out after opening the second PDF save
dialog. Page 1 and the draft XML existed, but page 2 and the merged PDF did not.
The six wait/populate/save references now target a separate `Save Print Output As`
window selector instead of nesting that dialog under the BIR form window.
The installed flow retains 116 actions, 21 inputs, and 3 outputs; its action
code was copied back and compared with the repair before retrying.

Backups and exports are outside Git in `../outputs/`:
- `Stage1_Prepare_2550Q-before-20261021.pad.txt`
- `Stage1_Prepare_2550Q-installed-20261021.pad.txt`, SHA-256
  `594f2759bb3a447d891c3d3f260a5db6678c85cf029bc2febdd966fd45ed9e8b`
- `eBIR_Work_Order_Agent-before-20261021.pad.txt`

The parent designer had been open since 18 October, consumed approximately one
CPU core, and took 10–15 seconds between simple debugger statements. Its stop
and close controls became unresponsive. With preparation still `ReadyToRun`,
no eBIR process, and no active submission, its runtime was stopped and the saved
dispatcher restarted using **Run in the Power Automate console**, rather than
the designer. Prefer console execution for normal queue processing; reserve
the designer for editing and debugging. This observation does not establish
that all earlier stops had the same cause.

The interrupted, unsubmitted XML was preserved under the worker's
`archive/recovery-20261021-dfb441ba` directory. Recovery used version checks,
attempt-state checks, and audit events; no submission was replayed.

Verification: the queued CHANG FENG 2550Q Q3 2026 preparation succeeded on
attempt `dac878b7-e97b-45b7-b62c-7a343f436483`. Both page PDFs and the merged
843,086-byte PDF were generated, and the server recorded
`AWAITING_SUBMISSION_APPROVAL` (version 15). The console dispatcher then
automatically started the next queued 2550Q preparation. An intervening 2551Q
preparation also completed. No tax submission was used as a test.
