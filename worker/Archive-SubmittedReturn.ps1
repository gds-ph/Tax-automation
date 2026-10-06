# Preview by default. -Commit archives only an API-confirmed successful attempt.
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\worker.json'),
    [string]$ReceiptPath = (Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\stage2-journal.json'),
    [string]$SaveFolder = 'C:\eBIRForms\savefile',
    [string]$ArchiveRoot = 'C:\TaxAutomation\Archive\Submitted',
    [switch]$Commit
)
$ErrorActionPreference = 'Stop'
$receipt = Get-Content -LiteralPath $ReceiptPath -Raw | ConvertFrom-Json
$claim = $receipt.Claim
$success = 'SUBMITTED_WAITING_FOR_CONFIRMATION'
if ($receipt.Phase -ne 'Completed' -or $receipt.Result.SubmissionStatus -ne $success -or
    $claim.AutomationKey -notin @('SUBMIT_2551QV2018','SUBMIT_1601CV2018','SUBMIT_1601EQ','SUBMIT_0619F','SUBMIT_1600VT') -or
    [string]$receipt.Result.AttemptId -cne [string]$claim.AttemptId) {
    throw 'A completed live submission receipt is required. Do not rerun submission.'
}
$attemptId = ([guid]$claim.AttemptId).ToString()
$orderId = [string]$claim.WorkOrderId
if ($orderId -notmatch '^WO-[A-Za-z0-9-]+$') { throw 'Invalid work order identifier.' }
$source = [IO.Path]::GetFullPath([string]$claim.ExpectedXmlPath)
$saveRoot = [IO.Path]::GetFullPath($SaveFolder).TrimEnd('\')
if ([IO.Path]::GetDirectoryName($source) -ine $saveRoot -or
    [IO.Path]::GetExtension($source) -ine '.xml' -or
    $source -ine [IO.Path]::GetFullPath([string]$claim.Inputs.ApprovedXmlPath) -or
    [IO.Path]::GetFileNameWithoutExtension($source) -cne [string]$claim.Inputs.ApprovedSavedReturnName) {
    throw 'Source does not match the approved XML in the save folder.'
}
$root = [IO.Path]::GetFullPath($ArchiveRoot).TrimEnd('\')
$folder = [IO.Path]::GetFullPath((Join-Path $root $orderId))
$destination = Join-Path $folder ([IO.Path]::GetFileName($source))
$manifestPath = Join-Path $folder ($attemptId + '.archive.json')
if (-not $folder.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $folder -ieq $saveRoot -or $folder.StartsWith($saveRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Archive must be outside the working save folder.'
}
function Assert-NoReparse([string]$Path) {
    $cursor = $Path
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Archive paths must not contain symbolic links or junctions.'
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
Assert-NoReparse $source
Assert-NoReparse $destination
Assert-NoReparse $manifestPath

# Replaying the result endpoint only verifies/reports a result; it never runs PAD.
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$base = ([string]$config.ApiBaseUrl).TrimEnd('/')
$uri = [Uri]$base
if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/' -or
    ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1')))) {
    throw 'Invalid worker API URL.'
}
$route = '/api/agent/stage2/' + $attemptId + '/result/'
try {
    $response = Invoke-WebRequest -Uri ($base + $route) -Method Post -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 60 `
        -Headers @{Authorization=('Bearer ' + [string]$config.Token)} -ContentType 'application/json' `
        -Body (@{lease_token=$claim.LeaseToken; SubmissionStatus=$success} | ConvertTo-Json)
    $confirmed = $response.Content | ConvertFrom-Json
} catch { throw 'Could not verify submission with the server. XML was not moved. Do not resubmit.' }
if ($confirmed.Status -ne $success -or $confirmed.SubmissionEnabled -ne $true) {
    throw 'Server has not confirmed successful live submission.'
}

$lock = $null
try {
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        # Refuse an XML open for writing. Hold this read lock through copy and verification.
        $lock = [IO.File]::Open($source, 'Open', 'Read', 'Read')
        $hasher = [Security.Cryptography.SHA256]::Create()
        try { $hash = [BitConverter]::ToString($hasher.ComputeHash($lock)).Replace('-','').ToLowerInvariant() }
        finally { $hasher.Dispose() }
        $lock.Position = 0
        if (Test-Path -LiteralPath $manifestPath) {
            $existing = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
            if ($existing.AttemptId -ne $attemptId -or $existing.Sha256 -cne $hash) {
                throw 'XML differs from its archive receipt. Working copy retained.'
            }
        }
        if (Test-Path -LiteralPath $destination) {
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
                throw 'Archive already contains different data. Working copy retained.'
            }
        }
        if (-not $Commit) {
            @{Mode='Preview'; Source=$source; ArchivePath=$destination; Sha256=$hash; SourceRemoved=$false} | ConvertTo-Json
            return
        }
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        if (-not (Test-Path -LiteralPath $destination)) {
            $copy = [IO.File]::Open($destination, 'CreateNew', 'Write', 'None')
            try { $lock.CopyTo($copy); $copy.Flush($true) } finally { $copy.Dispose() }
        }
        if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
            throw 'Archive verification failed. Working copy retained.'
        }
        $manifest = @{AttemptId=$attemptId; WorkOrderId=$orderId; Source=$source; ArchivePath=$destination;
                      Sha256=$hash; SubmissionStatus=$success; State='Copied'; UpdatedAt=[DateTime]::UtcNow.ToString('o')}
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
        $lock.Dispose(); $lock=$null
        # Recheck immediately before removing this exact file; never remove folders or use wildcards.
        if ((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
            throw 'Working XML changed during archiving. Working copy retained.'
        }
        Remove-Item -LiteralPath $source
        $manifest.State='Archived'
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    } else {
        if (-not (Test-Path -LiteralPath $manifestPath) -or -not (Test-Path -LiteralPath $destination)) {
            throw 'Working XML is missing and no verified archive receipt exists.'
        }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.AttemptId -ne $attemptId -or $manifest.Source -ine $source -or
            $manifest.ArchivePath -ine $destination -or
            (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant() -cne $manifest.Sha256) {
            throw 'Existing archive receipt or content does not match.'
        }
    }
    @{Archived=$true; ArchivePath=$destination; SourceRemoved=$true; SubmissionStatus=$success} | ConvertTo-Json
} finally { if ($null -ne $lock) { $lock.Dispose() } }
