# Run as the same Windows user as PAD, with the parent flow stopped.
# Add the PAD 1600VT branch and output mapping BEFORE installing this capability.
[CmdletBinding()]
param([string]$WorkerFolder = 'C:\TaxAutomation')
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($WorkerFolder)
if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Worker folder does not exist.' }
$configPath = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\worker.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$files = @('WorkerBridge.ps1')
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) { throw "Missing package file: $name" }
    if (-not (Test-Path -LiteralPath (Join-Path $target $name))) { throw "Missing installed bridge: $name" }
}
$backup = Join-Path $target ('Backup-1600VT-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $target $name) -Destination (Join-Path $backup $name) }
# The configuration backup stays beside the original private configuration.
$configBackup = $configPath + '.before-1600vt-' + [guid]::NewGuid().ToString('N')
Copy-Item -LiteralPath $configPath -Destination $configBackup
$preparation = @('PREPARE_2551QV2018_ZERO')
if ($config.PSObject.Properties.Name -contains 'PreparationAutomationKeys') { $preparation = @($config.PreparationAutomationKeys) }
$config | Add-Member -NotePropertyName PreparationAutomationKeys -NotePropertyValue @(@($preparation + 'PREPARE_1600VT_ZERO') | Select-Object -Unique) -Force
try {
    foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $target $name) -Force }
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
} catch {
    foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name) -Force }
    Copy-Item -LiteralPath $configBackup -Destination $configPath -Force
    throw 'Install failed; prior scripts and configuration restored.'
}
Write-Output '1600VT capability installed. Existing credentials, capabilities and journals preserved.'
Write-Output "Bridge backup: $backup"