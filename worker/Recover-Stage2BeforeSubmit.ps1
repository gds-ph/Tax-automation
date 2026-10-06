# Use only AFTER audited server recovery of this exact attempt, with PAD stopped.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][guid]$AttemptId,
    [string]$WorkerFolder = (Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker')
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($WorkerFolder)
$journalPath = Join-Path $root 'stage2-journal.json'
$hasher = [Security.Cryptography.SHA256]::Create()
$digest = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes((Join-Path $root 'journal.json').ToLowerInvariant()))).Replace('-', '')
$hasher.Dispose()
$mutex = [Threading.Mutex]::new($false, ('Local\eBIRWorker-' + $digest))
$held = $false
try {
    try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { throw 'A worker operation is active. Stop PAD first.' }
    $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json
    if ($journal.Phase -ne 'Running' -or [string]$journal.Claim.AttemptId -ne $AttemptId.ToString() -or $journal.Result) {
        throw 'Journal no longer matches the confirmed stopped-before-submit attempt. Nothing changed.'
    }
    $screenshot = [string]$journal.Claim.Inputs.SuccessScreenshotPath
    if ($screenshot -and (Test-Path -LiteralPath $screenshot)) { throw 'Submission screenshot exists. Recovery refused.' }
    $resultPath = Join-Path $root 'stage2-result.json'
    if (Test-Path -LiteralPath $resultPath) {
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ([string]$result.AttemptId -eq $AttemptId.ToString()) { throw 'A result exists for this attempt. Review it before recovery.' }
    }
    # Retain the complete old journal locally (contains a lease token; never share).
    $backup = Join-Path $root ('stage2-before-submit-' + $AttemptId.ToString() + '-' + [guid]::NewGuid().ToString() + '.json')
    Copy-Item -LiteralPath $journalPath -Destination $backup
    if ((Get-FileHash -LiteralPath $journalPath).Hash -ne (Get-FileHash -LiteralPath $backup).Hash) {
        throw 'Journal backup verification failed. Active journal unchanged.'
    }
    $fresh = @{ RequestId=[guid]::NewGuid().ToString(); Phase='Requesting'; Claim=$null; Result=$null }
    $pending = Join-Path $root 'stage2-journal.pending.json'
    [IO.File]::WriteAllText($pending, ($fresh | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $pending -Destination $journalPath -Force
    @{RecoveredBeforeSubmit=$true; OldAttemptId=$AttemptId.ToString(); JournalPreserved=$true} | ConvertTo-Json
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
