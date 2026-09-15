# Run only inside the VM after both PAD flows and eBIRForms are closed.
# Archives ABC TEST COMPANY, TIN 65070331200000, 2551Qv2018, 2026 Q1-Q4.
$ErrorActionPreference = 'Stop'
$orderIds = @('ce69380f-4993-4b6f-8be9-030df1cc444e','eba7fd2d-821a-472b-b8d5-7a1d94fc24d3','f9cc6d4e-c70d-4f21-84a5-a89d232a4130','3b03ecf6-f340-4d21-a590-73d818b5bb65','9060c644-1ce4-454b-8433-ea74b748070b')
$orderIds += 'fef6e9a7-db66-4f7e-9a31-605bb84d632f'
$workerDir = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker'
$journalPath = Join-Path $workerDir 'journal.json'
if (Test-Path -LiteralPath $journalPath) {
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    $allowedNames = @($orderIds | ForEach-Object { 'WO-2026-' + $_.Replace('-', '') })
    if ($journal.Claim -and [string]$journal.Claim.WorkOrderId -notin $allowedNames) {
        throw 'The journal belongs to another work order. Nothing was changed.'
    }
}
$archive = Join-Path $workerDir ('archive\demo-2026-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $archive | Out-Null
$ownerSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls.exe $archive /inheritance:r /grant:r "*${ownerSid}:(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not protect archive directory.' }
function Preserve-Item([string]$source, [string]$root, [string]$name) {
    $fullSource = [IO.Path]::GetFullPath($source)
    $fullRoot = [IO.Path]::GetFullPath($root).TrimEnd('\') + '\'
    if (!$fullSource.StartsWith($fullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Source is outside the intended directory.'
    }
    if (Test-Path -LiteralPath $fullSource) {
        $item = Get-Item -LiteralPath $fullSource
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked paths require manual review.' }
        $destination = Join-Path $archive $name
        if (Test-Path -LiteralPath $destination) { throw 'Archive destination collision.' }
        Move-Item -LiteralPath $fullSource -Destination $destination
        Write-Output "Archived: $name"
    }
}
foreach ($quarter in 1..4) {
    $name = "65070331200000-2551Qv2018-122026Q$quarter.xml"
    Preserve-Item (Join-Path 'C:\eBIRForms\savefile' $name) 'C:\eBIRForms\savefile' $name
}
foreach ($orderId in $orderIds) {
    Preserve-Item (Join-Path 'C:\TaxAutomation\Working' $orderId) 'C:\TaxAutomation\Working' $orderId
}
# Earlier manual fake-data runs may have written PDFs directly in Working.
if (Test-Path -LiteralPath 'C:\TaxAutomation\Working') {
    Get-ChildItem -LiteralPath 'C:\TaxAutomation\Working' -File | Where-Object {
        $_.Name -cmatch '^ABC_TEST_COMPANY_2551Q_2026_Q[1-4](?:_[A-Za-z0-9_-]+)?\.pdf$'
    } | ForEach-Object { Preserve-Item $_.FullName 'C:\TaxAutomation\Working' $_.Name }
}
# Preserve the journal last. Credentials and older archives stay in place.
foreach ($name in @('result.json','journal.pending.json','journal.json')) {
    Preserve-Item (Join-Path $workerDir $name) $workerDir $name
}
Write-Output "Reset complete. Files preserved in: $archive"
Write-Output 'Create fresh 2026 Q1-Q4 tasks from the dashboard. worker.json and eBIRForms profile were preserved.'
