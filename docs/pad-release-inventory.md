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

1. Back up the installed parent and child flows, local configuration and journals in restricted storage.
2. Select the export for the intended form and compare its checksum to this inventory. Older similarly named files are historical candidates, not automatic fallbacks.
3. Install the matching repository bridges and validators, then import or paste the reviewed PAD flow in the desktop editor.
4. Verify child-flow names, input variables, installed eBIRForms version, UI selectors and local paths. Preserve all existing worker capabilities when adding a new capability.
5. Test with a designated test client through preparation and PDF/XML verification. Keep submission separately approved; preparation success is not submission verification.
6. Record the new export, checksum and actual test outcome whenever PAD is edited.

See [system guide](current-system-guide.md) for worker contracts and recovery, and [documentation index](README.md) for form-specific setup.
