[CmdletBinding()]
param([string]$WorkerFolder='C:\TaxAutomation')
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($WorkerFolder)
if (-not (Test-Path -LiteralPath (Join-Path $root 'WorkerBridge.ps1'))) { throw 'Existing worker installation not found.' }
$names=@('WorkerBridge.ps1','Archive-CancelledReturn.ps1')
foreach ($name in $names) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) { throw 'Extract the entire ZIP first.' }
}
$backup=Join-Path $root ('Backup-CancellationCleanup-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in $names) {
    $target=Join-Path $root $name
    if (Test-Path -LiteralPath $target) { Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name) }
}
try {
    foreach ($name in $names) {
        $source=Join-Path $PSScriptRoot $name; $target=Join-Path $root $name
        Copy-Item -LiteralPath $source -Destination $target -Force
        if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) { throw 'Installation verification failed.' }
    }
} catch {
    foreach ($name in $names) {
        $original=Join-Path $backup $name
        if (Test-Path -LiteralPath $original) { Copy-Item -LiteralPath $original -Destination (Join-Path $root $name) -Force }
    }
    throw
}
Write-Output 'Cancellation cleanup installed. Credentials and journals preserved.'
Write-Output 'Close eBIRForms form windows, then start one parent PAD worker.'
