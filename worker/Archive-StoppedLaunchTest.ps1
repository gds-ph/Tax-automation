# Run inside the automation VM with both PAD flows stopped.
# This specific attempt has already been abandoned on the dashboard.
# Never use this script to reset a different attempt.
$ErrorActionPreference = 'Stop'
$attemptId = '2c5f769e-4671-4b18-9ebb-a58306840820'
$workerDirectory = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker'
$journalFile = Join-Path $workerDirectory 'journal.json'
$archiveDirectory = Join-Path $workerDirectory ('archive\' + $attemptId)
if (!(Test-Path -LiteralPath $journalFile -PathType Leaf)) {
    throw 'No active journal found. Do not rerun the archive procedure.'
}
$journal = Get-Content -LiteralPath $journalFile -Raw | ConvertFrom-Json
if ([string]$journal.Claim.AttemptId -cne $attemptId) {
    throw 'Journal belongs to a different attempt. Nothing was archived.'
}
New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null
# Preserve private lease data with the same per-user protection as worker.json.
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls.exe $archiveDirectory /inheritance:r /grant:r "*${ownerSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect archive folder.' }
$oldOutput = 'C:\TaxAutomation\Working\f9cc6d4e-c70d-4f21-84a5-a89d232a4130\2c5f769e-4671-4b18-9ebb-a58306840820'
$resolvedOutput = [IO.Path]::GetFullPath($oldOutput)
if (!$resolvedOutput.StartsWith('C:\TaxAutomation\Working\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Output folder is outside the expected VM working root.'
}
$items = @(
    @{ Source = 'C:\eBIRForms\savefile\65070331200000-2551Qv2018-122026Q1.xml'; Name = '65070331200000-2551Qv2018-122026Q1.xml' },
    @{ Source = $resolvedOutput; Name = 'partial-output' },
    @{ Source = (Join-Path $workerDirectory 'result.json'); Name = 'result.json' },
    @{ Source = (Join-Path $workerDirectory 'journal.pending.json'); Name = 'journal.pending.json' },
    # Move the active journal last, only after partial artifacts are preserved.
    @{ Source = $journalFile; Name = 'journal.json' }
)
foreach ($item in $items) {
    if (Test-Path -LiteralPath $item.Source) {
        $destination = Join-Path $archiveDirectory $item.Name
        if (Test-Path -LiteralPath $destination) { throw 'Archive destination already exists. Stop and inspect; do not overwrite.' }
        Move-Item -LiteralPath $item.Source -Destination $destination
    }
}
Write-Output "Stopped attempt archived in $archiveDirectory"
Write-Output 'Ready for one fresh fake-data wrapper run. worker.json was preserved.'
