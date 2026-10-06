# Run as the same Windows user as PAD, with the parent flow stopped.
[CmdletBinding()]
param([string]$WorkerFolder = 'C:\TaxAutomation')
$ErrorActionPreference = 'Stop'
$target = [IO.Path]::GetFullPath($WorkerFolder)
if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Worker folder does not exist.' }
$configPath = Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\worker.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$files = @('WorkerBridge.ps1','Stage2Bridge.ps1','Archive-SubmittedReturn.ps1')
foreach ($name in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $name))) { throw "Missing package file: $name" }
    if (-not (Test-Path -LiteralPath (Join-Path $target $name))) { throw "Missing installed bridge: $name" }
}
$backup = Join-Path $target ('Backup-0619F-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $backup | Out-Null
foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $target $name) -Destination (Join-Path $backup $name) }
# The configuration backup stays beside the original private configuration.
$configBackup = $configPath + '.before-0619f-' + [guid]::NewGuid().ToString('N')
Copy-Item -LiteralPath $configPath -Destination $configBackup
$preparation = @('PREPARE_2551QV2018_ZERO')
$submission = @('REVALIDATE_2551QV2018','SUBMIT_2551QV2018')
if ($config.PSObject.Properties.Name -contains 'PreparationAutomationKeys') { $preparation = @($config.PreparationAutomationKeys) }
if ($config.PSObject.Properties.Name -contains 'Stage2AutomationKeys') { $submission = @($config.Stage2AutomationKeys) }
$config | Add-Member -NotePropertyName PreparationAutomationKeys -NotePropertyValue @(@($preparation + 'PREPARE_0619F_ZERO') | Select-Object -Unique) -Force
$config | Add-Member -NotePropertyName Stage2AutomationKeys -NotePropertyValue @(@($submission + 'SUBMIT_0619F') | Select-Object -Unique) -Force
try {
    foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination (Join-Path $target $name) -Force }
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
} catch {
    foreach ($name in $files) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination (Join-Path $target $name) -Force }
    Copy-Item -LiteralPath $configBackup -Destination $configPath -Force
    throw 'Install failed; prior scripts and configuration restored.'
}
Write-Output '0619F capability installed. Existing credentials, capabilities and journals preserved.'
Write-Output "Bridge backup: $backup"
