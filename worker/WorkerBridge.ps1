# Windows PowerShell 5.1+. Runs inside the automation VM alongside PAD.
# This bridge transfers tasks/results; it never launches PAD or submits a return.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('Health','Poll','Start','Publish','Renew')][string]$Action,
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\worker.json')
)
$ErrorActionPreference = 'Stop'
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$workerFolder = [IO.Path]::GetDirectoryName($configFile)
$journalPath = [IO.Path]::Combine($workerFolder, 'journal.json')
$resultPath = [IO.Path]::Combine($workerFolder, 'result.json')
# Serialize all bridge invocations sharing this journal, including Start checks.
$pathHasher = [Security.Cryptography.SHA256]::Create()
$pathDigest = [BitConverter]::ToString($pathHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($journalPath.ToLowerInvariant()))).Replace('-', '')
$pathHasher.Dispose()
$workerMutex = [Threading.Mutex]::new($false, ('Local\eBIRWorker-' + $pathDigest))
$mutexHeld = $false
try {
    try { $mutexHeld = $workerMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexHeld = $true }
    if (-not $mutexHeld) { throw 'Another worker operation is running. Start only one agent flow per VM.' }
$config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
$apiRoot = ([string]$config.ApiBaseUrl).TrimEnd('/')
$apiUri = [Uri]$apiRoot
if ($apiUri.UserInfo -or $apiUri.Query -or $apiUri.Fragment -or $apiUri.AbsolutePath -ne '/') { throw 'Invalid API base URL.' }
if ($apiUri.Scheme -ne 'https' -and -not ($apiUri.Scheme -eq 'http' -and $apiUri.Host -in @('127.0.0.1','localhost'))) {
    throw 'Use HTTPS for VM networking. HTTP is reserved for loopback tests.'
}
$headers = @{ Authorization = 'Bearer ' + [string]$config.Token }

function Invoke-WorkerApi([string]$Method, [string]$Route, $Body) {
    if (-not $Route.StartsWith('/api/agent/')) { throw 'Invalid API route.' }
    $parameters = @{ Uri=$apiRoot+$Route; Method=$Method; Headers=$headers; TimeoutSec=60; UseBasicParsing=$true; MaximumRedirection=0 }
    if ($null -ne $Body) { $parameters.ContentType='application/json; charset=utf-8'; $parameters.Body=[Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 12 -Compress)) }
    try {
        $response = Invoke-WebRequest @parameters
        if ($response.StatusCode -eq 204) { return $null }
        return ($response.Content | ConvertFrom-Json)
    } catch {
        # Keep the original request/journal for retry. Never print bearer headers.
        $retryable = $false
        $failure = $_.Exception
        if ($failure -is [Net.WebException]) {
            if ($null -ne $failure.Response) {
                $statusCode = [int]$failure.Response.StatusCode
                $retryable = $statusCode -in @(408,429,500,502,503,504)
            } else {
                $retryable = $failure.Status -in @(
                    [Net.WebExceptionStatus]::Timeout,
                    [Net.WebExceptionStatus]::ConnectFailure,
                    [Net.WebExceptionStatus]::NameResolutionFailure,
                    [Net.WebExceptionStatus]::ConnectionClosed,
                    [Net.WebExceptionStatus]::ReceiveFailure,
                    [Net.WebExceptionStatus]::SendFailure,
                    [Net.WebExceptionStatus]::KeepAliveFailure)
            }
        }
        $safeError = [Exception]::new('Worker API request failed. Preserve the journal; check server status before retrying the same operation.')
        $safeError.Data['Retryable'] = $retryable
        throw $safeError
    }
}

function Write-Journal($Value) {
    $temporaryPath = [IO.Path]::Combine($workerFolder, 'journal.pending.json')
    [IO.File]::WriteAllText($temporaryPath, ($Value | ConvertTo-Json -Depth 15), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporaryPath -Destination $journalPath -Force
}

function Public-Claim($Value) {
    return @{ HasTask=$true; RecoveryRequired=$false; AttemptId=$Value.AttemptId; WorkOrderId=$Value.WorkOrderId;
        AutomationKey=$Value.AutomationKey; Inputs=$Value.Inputs; ExpectedXmlPath=$Value.ExpectedXmlPath;
        ExpectedPdfPath=$Value.ExpectedPdfPath; LeaseExpiresAt=$Value.LeaseExpiresAt }
}

if ($Action -eq 'Health') {
    Invoke-WorkerApi 'GET' '/api/agent/health/' $null | ConvertTo-Json -Depth 5
    return
}
$journal = $null
if (Test-Path -LiteralPath $journalPath) { $journal = Get-Content -LiteralPath $journalPath -Raw | ConvertFrom-Json }
if ($Action -eq 'Poll') {
    if ($null -ne $journal -and $journal.Phase -in @('Running','Publishing')) {
        @{ HasTask=$false; RecoveryRequired=$true; Message='An earlier task was started. Do not rerun Tax-Filing. Resume reporting or request operator review.' } | ConvertTo-Json
        return
    }
    if ($null -eq $journal -or $journal.Phase -eq 'Completed') {
        $journal = [pscustomobject]@{ RequestId=[guid]::NewGuid().ToString(); Phase='Requesting'; Claim=$null; Result=$null }
        Write-Journal $journal
    }
    # Repeating this UUID recovers a lost claim response without claiming another job.
    $claim = Invoke-WorkerApi 'POST' '/api/agent/preparation/claim/' @{ request_id=$journal.RequestId; automation_keys=@('PREPARE_2551QV2018_ZERO') }
    if ($null -eq $claim) { @{ HasTask=$false; RecoveryRequired=$false } | ConvertTo-Json; return }
    if ($claim.State -ne 'RUNNING') {
        $journal.Phase='Completed'; Write-Journal $journal
        @{ HasTask=$false; RecoveryRequired=$false; Message='Previous request already finished.' } | ConvertTo-Json
        return
    }
    $journal.Claim=$claim; $journal.Phase='ReadyToRun'; Write-Journal $journal
    Public-Claim $claim | ConvertTo-Json -Depth 12
    return
}
if ($null -eq $journal -or $null -eq $journal.Claim) { throw 'No claimed job in the local journal.' }
$claim = $journal.Claim
if ($Action -eq 'Start') {
    if ($journal.Phase -ne 'ReadyToRun') { throw 'This job was already started or is not ready. Never run Tax-Filing twice.' }
    if ($claim.AutomationKey -ne 'PREPARE_2551QV2018_ZERO') { throw 'Unsupported automation key.' }
    $renewal=Invoke-WorkerApi 'POST' $claim.RenewUrl @{ lease_token=$claim.LeaseToken }
    $claim.LeaseExpiresAt=$renewal.LeaseExpiresAt
    [IO.Directory]::CreateDirectory([string]$claim.Inputs.OutputFolder) | Out-Null
    $journal.Phase='Running'; Write-Journal $journal
    @{ Started=$true } | ConvertTo-Json
    return
}
if ($Action -eq 'Renew') {
    if ($journal.Phase -notin @('Running','ReadyToRun','Publishing')) { throw 'No active attempt to renew.' }
    $renewal=Invoke-WorkerApi 'POST' $claim.RenewUrl @{ lease_token=$claim.LeaseToken }
    $claim.LeaseExpiresAt=$renewal.LeaseExpiresAt;Write-Journal $journal
    $renewal | ConvertTo-Json
    return
}
if ($Action -eq 'Publish') {
    if ($journal.Phase -eq 'Completed') { @{ Recorded=$true; Message='Already recorded.' } | ConvertTo-Json; return }
    if ($journal.Phase -notin @('Running','Publishing')) { throw 'Tax-Filing has not been started for this job.' }
    if ($journal.Phase -eq 'Running') {
        $outputs=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ([string]$outputs.AttemptId -cne [string]$claim.AttemptId) { throw 'The result file belongs to another attempt.' }
        $journal.Result=$outputs; $journal.Phase='Publishing';Write-Journal $journal
    }
    $outputs=$journal.Result
    if ($outputs.PreparationStatusOutput -eq 'AWAITING_SUBMISSION_APPROVAL') {
        if ([string]$outputs.PreparedPdfPath -cne [string]$claim.ExpectedPdfPath -or [string]$outputs.SavedXmlPath -cne [string]$claim.ExpectedXmlPath) {
            throw 'Result paths do not match this claimed task. Do not upload other files.'
        }
        if (-not (Test-Path -LiteralPath $outputs.PreparedPdfPath -PathType Leaf) -or -not (Test-Path -LiteralPath $outputs.SavedXmlPath -PathType Leaf)) {
            throw 'Both the VM-local XML and merged PDF must exist.'
        }
        $pdfInfo=Get-Item -LiteralPath $outputs.PreparedPdfPath
        if ($pdfInfo.Length -gt 25MB) { throw 'PDF exceeds 25 MiB.' }
        $hash=(Get-FileHash -LiteralPath $outputs.PreparedPdfPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $uploadHeaders=@{ Authorization=$headers.Authorization; 'X-Lease-Token'=$claim.LeaseToken; 'X-PDF-SHA256'=$hash }
        try {
            Invoke-WebRequest -UseBasicParsing -Uri ($apiRoot+$claim.PdfUploadUrl) -Method Put -Headers $uploadHeaders -ContentType 'application/pdf' -InFile $outputs.PreparedPdfPath -TimeoutSec 120 -MaximumRedirection 0 | Out-Null
        } catch { throw 'PDF upload failed. Retry Publish only; do not rerun Tax-Filing.' }
    }
    $result=Invoke-WorkerApi 'POST' $claim.ResultUrl @{
        lease_token=$claim.LeaseToken; PreparationStatusOutput=[string]$outputs.PreparationStatusOutput;
        PreparedPdfPath=[string]$outputs.PreparedPdfPath; SavedXmlPath=[string]$outputs.SavedXmlPath
    }
    $journal.Phase='Completed';Write-Journal $journal
    $result | ConvertTo-Json -Depth 5
}

} catch {
    if ($Action -ne 'Poll') { throw }
    # PAD must receive JSON even when polling fails. Only transient API failures
    # may follow the existing HasTask=False -> Wait -> Next loop path.
    $canRetry = $_.Exception.Data['Retryable'] -eq $true
    @{
        HasTask=$false
        RecoveryRequired=(-not $canRetry)
        Retryable=$canRetry
        Message=$(if ($canRetry) { 'Temporary connection or server failure. Retry polling with the existing journal.' }
                  else { 'Worker polling failed. Check configuration and journal; operator review is required.' })
    } | ConvertTo-Json
} finally {
    if ($mutexHeld) { $workerMutex.ReleaseMutex() }
    $workerMutex.Dispose()
}
