$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Project Python environment is missing.' }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"' + (Join-Path $project 'manage.py') + '" check_bir_receipts') -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName 'TaxAutomation-BIRReceipts' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Discover submitted filings every five minutes; check each pending BIR receipt every three hours.' -Force | Out-Null
Write-Output 'Installed TaxAutomation-BIRReceipts. Runs while this Windows user is signed in.'
