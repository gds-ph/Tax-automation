# Install while the parent and child PAD flows are stopped.
[CmdletBinding()]
param([string]$WorkerFolder = 'C:\TaxAutomation')
$ErrorActionPreference = 'Stop'
$target = Join-Path ([IO.Path]::GetFullPath($WorkerFolder)) 'WorkerBridge.ps1'
$source = Join-Path $PSScriptRoot 'WorkerBridge.ps1'
if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Installed worker bridge not found: $target" }
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Extract the entire update ZIP first.' }
$backup = $target + '.before-dashboard-recovery-' + [guid]::NewGuid().ToString('N') + '.bak'
Copy-Item -LiteralPath $target -Destination $backup
try {
    Copy-Item -LiteralPath $source -Destination $target -Force
    if ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
        throw 'Installed file verification failed.'
    }
} catch {
    Copy-Item -LiteralPath $backup -Destination $target -Force
    throw
}
Write-Output 'Dashboard recovery installed. Configuration and pending journals preserved.'
Write-Output "Backup: $backup"
Write-Output 'Release the interrupted run in the dashboard, then start one parent worker.'
