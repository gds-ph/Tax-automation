# Windows PowerShell 5.1+. Runs inside the automation VM alongside PAD.
# This bridge transfers tasks/results; it never launches PAD or submits a return.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('Health','Poll','Start','Publish','Renew','Archive','Reconcile')][string]$Action,
    [string]$ConfigPath = (Join-Path $env:LOCALAPPDATA 'TaxAutomationWorker\worker.json'),
    [string]$ArchiveHelperPath = 'C:\TaxAutomation\Archive-SubmittedReturn.ps1',
    [string]$SaveFolder = 'C:\eBIRForms\savefile',
    [string]$ArchiveRoot = 'C:\TaxAutomation\Archive\Submitted'
)
$ErrorActionPreference = 'Stop'
$configFile = [IO.Path]::GetFullPath($ConfigPath)
$workerFolder = [IO.Path]::GetDirectoryName($configFile)
$journalPath = [IO.Path]::Combine($workerFolder, 'journal.json')
$resultPath = [IO.Path]::Combine($workerFolder, 'stage2-result.json')
# Serialize all bridge invocations sharing this journal, including Start checks.
$pathHasher = [Security.Cryptography.SHA256]::Create()
$pathDigest = [BitConverter]::ToString($pathHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($journalPath.ToLowerInvariant()))).Replace('-', '')
$pathHasher.Dispose()
$workerMutex = [Threading.Mutex]::new($false, ('Local\eBIRWorker-' + $pathDigest))
$journalPath = [IO.Path]::Combine($workerFolder, 'stage2-journal.json')
$mutexHeld = $false
try {
    try { $mutexHeld = $workerMutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $mutexHeld = $true }
    if (-not $mutexHeld) { throw 'Another worker operation is running. Start only one agent flow per VM.' }
$config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json
$automationKeys = @('REVALIDATE_2551QV2018','SUBMIT_2551QV2018')
if ($config.PSObject.Properties.Name -contains 'Stage2AutomationKeys') {
    $automationKeys = @($config.Stage2AutomationKeys)
}
$allowedAutomationKeys = @('REVALIDATE_2551QV2018','SUBMIT_2551QV2018','SUBMIT_1601CV2018','SUBMIT_1601EQ','SUBMIT_0619F','SUBMIT_1600VT')
if ($automationKeys.Count -eq 0 -or @($automationKeys | Where-Object { $_ -notin $allowedAutomationKeys }).Count -gt 0 -or @($automationKeys | Select-Object -Unique).Count -ne $automationKeys.Count) {
    throw 'Invalid configured automation keys.'
}

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
    $temporaryPath = [IO.Path]::Combine($workerFolder, 'stage2-journal.pending.json')
    [IO.File]::WriteAllText($temporaryPath, ($Value | ConvertTo-Json -Depth 15), (New-Object Text.UTF8Encoding($false)))
    Move-Item -LiteralPath $temporaryPath -Destination $journalPath -Force
}

function Save-SubmissionReceipt($Value) {
    if ($Value.Result.SubmissionStatus -eq 'SUBMITTED_WAITING_FOR_CONFIRMATION') {
        # Contains a lease token: keep local, never include contents in logs.
        $receiptFolder = Join-Path $workerFolder 'submitted'
        New-Item -ItemType Directory -Path $receiptFolder -Force | Out-Null
        $receiptPath = Join-Path $receiptFolder (([guid]$Value.Claim.AttemptId).ToString() + '.json')
        $receipt = $Value | ConvertTo-Json -Depth 15 | ConvertFrom-Json
        # ArchivePending means the API has already accepted the submission.
        if ($receipt.Phase -eq 'ArchivePending') { $receipt.Phase = 'Completed' }
        [IO.File]::WriteAllText($receiptPath, ($receipt | ConvertTo-Json -Depth 15), [Text.UTF8Encoding]::new($false))
    }
}

function Complete-Archive {
    if ($journal.Phase -ne 'ArchivePending' -or
        $journal.Result.SubmissionStatus -ne 'SUBMITTED_WAITING_FOR_CONFIRMATION') {
        throw 'No pending archive. Do not rerun submission.'
    }
    try {
        Save-SubmissionReceipt $journal
        $receiptPath = Join-Path (Join-Path $workerFolder 'submitted') (([guid]$claim.AttemptId).ToString() + '.json')
        $archiveJson = & ([scriptblock]::Create([IO.File]::ReadAllText($ArchiveHelperPath))) `
            -ConfigPath $configFile -ReceiptPath $receiptPath -SaveFolder $SaveFolder -ArchiveRoot $ArchiveRoot -Commit
        $archive = $archiveJson | ConvertFrom-Json
        if ($archive.Archived -ne $true -or $archive.SourceRemoved -ne $true) { throw 'Archive did not complete.' }
        $journal | Add-Member -NotePropertyName ArchivePath -NotePropertyValue $archive.ArchivePath -Force
        $journal.Phase='Completed'; Write-Journal $journal
        Save-SubmissionReceipt $journal
        return @{Recorded=$true; Status=$journal.Result.SubmissionStatus; Archived=$true; ArchivePath=$archive.ArchivePath}
    } catch {
        throw 'Submission is already recorded. Archive recovery required: retry Stage2Bridge -Action Archive only; do not rerun the desktop submission flow.'
    }
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
    if ($null -ne $journal -and $journal.Phase -eq 'ArchivePending') {
        @{ HasTask=$false; RecoveryRequired=$true; Message='Submission recorded; archive pending. Retry Stage2Bridge -Action Archive only. Do not resubmit.' } | ConvertTo-Json
        return
    }
    if ($null -ne $journal -and $journal.Phase -eq 'Completed') { Save-SubmissionReceipt $journal }
    if ($null -ne $journal -and $journal.Phase -in @('Running','Publishing')) {
        @{ HasTask=$false; RecoveryRequired=$true; Message='An earlier task was started. Do not rerun Tax-Filing. Resume reporting or request operator review.' } | ConvertTo-Json
        return
    }
    if ($null -eq $journal -or $journal.Phase -eq 'Completed') {
        $journal = [pscustomobject]@{ RequestId=[guid]::NewGuid().ToString(); Phase='Requesting'; Claim=$null; Result=$null }
        Write-Journal $journal
    }
    # Repeating this UUID recovers a lost claim response without claiming another job.
    $claim = Invoke-WorkerApi 'POST' '/api/agent/stage2/claim/' @{ request_id=$journal.RequestId; automation_keys=$automationKeys }
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
if ($Action -eq 'Reconcile') {
    # Read the existing claim only; never request a new job during reconciliation.
    if ([string]$journal.RequestId -ne [string]$claim.AttemptId -or
        $journal.Phase -notin @('Running','Completed') -or $journal.Result) {
        throw 'Journal is not an interrupted, unreported attempt. Nothing changed.'
    }
    $reconciled = Invoke-WorkerApi 'POST' '/api/agent/stage2/claim/' @{
        request_id=$claim.AttemptId; automation_keys=$automationKeys
    }
    if ($null -eq $reconciled -or [string]$reconciled.AttemptId -ne [string]$claim.AttemptId -or
        $reconciled.State -ne 'ABANDONED' -or $reconciled.Status -ne 'MANUALLY_SUBMITTED_UNVERIFIED') {
        throw 'Server has not reconciled this exact manual submission. Nothing changed.'
    }
    $backupPath = Join-Path $workerFolder ('stage2-manual-' + ([guid]$claim.AttemptId).ToString() + '-' + [guid]::NewGuid().ToString() + '.json')
    Copy-Item -LiteralPath $journalPath -Destination $backupPath
    if ((Get-FileHash -LiteralPath $journalPath).Hash -ne (Get-FileHash -LiteralPath $backupPath).Hash) {
        throw 'Journal backup verification failed. Active journal unchanged.'
    }
    $journal | Add-Member -NotePropertyName ManualReconciliation -NotePropertyValue $reconciled.Status -Force
    $journal.Phase='Completed'; Write-Journal $journal
    @{Reconciled=$true; Status=$reconciled.Status; JournalPreserved=$true} | ConvertTo-Json
    return
}
if ($Action -eq 'Start') {
    if ($journal.Phase -ne 'ReadyToRun') { throw 'This job was already started or is not ready. Never run Tax-Filing twice.' }
    if ($claim.AutomationKey -notin $automationKeys) { throw 'Unsupported automation key.' }
    $renewal=Invoke-WorkerApi 'POST' $claim.RenewUrl @{ lease_token=$claim.LeaseToken }
    $claim.LeaseExpiresAt=$renewal.LeaseExpiresAt
    $isSubmission = $claim.AutomationKey -in @('SUBMIT_2551QV2018','SUBMIT_1601CV2018','SUBMIT_1601EQ','SUBMIT_0619F','SUBMIT_1600VT')
    if ($claim.Inputs.SubmissionEnabled -isnot [bool] -or $claim.Inputs.SubmissionEnabled -ne $isSubmission) { throw 'Approval mode mismatch.' }
    if ($claim.Inputs.ApprovedForSubmission -ne $true) { throw 'Approval is missing.' }
    if ((Get-FileHash -LiteralPath $claim.ExpectedPdfPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $claim.Inputs.ApprovedPdfSha256) { throw 'Approved PDF mismatch.' }
    if (-not (Test-Path -LiteralPath $claim.ExpectedXmlPath -PathType Leaf)) { throw 'Approved XML is missing.' }
    if ($isSubmission) {
        if (-not (Test-Path -LiteralPath $ArchiveHelperPath -PathType Leaf)) { throw 'Install Archive-SubmittedReturn.ps1 before starting submission.' }
        $expectedScreenshot = [IO.Path]::GetFullPath((Join-Path $claim.Inputs.OutputFolder 'submission-success.png'))
        if ([IO.Path]::GetFullPath($claim.Inputs.SuccessScreenshotPath) -cne $expectedScreenshot) { throw 'Screenshot destination mismatch.' }
        if (Test-Path -LiteralPath $expectedScreenshot) { throw 'Success screenshot already exists. Operator review required.' }
        New-Item -ItemType Directory -Path $claim.Inputs.OutputFolder -Force | Out-Null
    }
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
if ($Action -eq 'Archive') {
    if ($journal.Phase -eq 'Completed' -and $journal.ArchivePath) {
        @{Recorded=$true; Status=$journal.Result.SubmissionStatus; Archived=$true; ArchivePath=$journal.ArchivePath} | ConvertTo-Json
        return
    }
    Complete-Archive | ConvertTo-Json -Depth 5
    return
}
if ($Action -eq 'Publish') {
    if ($journal.Phase -eq 'ArchivePending') {
        Complete-Archive | ConvertTo-Json -Depth 5
        return
    }
    if ($journal.Phase -eq 'Completed') {
        Save-SubmissionReceipt $journal
        @{ Recorded=$true; Status=$journal.Result.SubmissionStatus; Archived=[bool]$journal.ArchivePath; ArchivePath=$journal.ArchivePath; Message='Already recorded.' } | ConvertTo-Json
        return
    }
    if ($journal.Phase -notin @('Running','Publishing')) { throw 'Tax-Filing has not been started for this job.' }
    if ($journal.Phase -eq 'Running') {
        $outputs=Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        if ([string]$outputs.AttemptId -cne [string]$claim.AttemptId) { throw 'The result file belongs to another attempt.' }
        $journal.Result=$outputs; $journal.Phase='Publishing';Write-Journal $journal
    }
    $outputs=$journal.Result
    if ($outputs.SubmissionStatus -eq 'SUBMITTED_WAITING_FOR_CONFIRMATION') {
        if ($claim.AutomationKey -notin @('SUBMIT_2551QV2018','SUBMIT_1601CV2018','SUBMIT_1601EQ','SUBMIT_0619F','SUBMIT_1600VT')) { throw 'This approval did not authorize submission.' }
        $screenshot = [IO.Path]::GetFullPath([string]$outputs.SuccessScreenshotPath)
        if ($screenshot -cne [IO.Path]::GetFullPath([string]$claim.Inputs.SuccessScreenshotPath)) { throw 'Screenshot belongs to another attempt.' }
        $imageFile = Get-Item -LiteralPath $screenshot
        if ($imageFile.Length -gt 10485760 -or $imageFile.Length -lt 33) { throw 'Invalid screenshot size.' }
        $uploadHeaders = @{ Authorization=$headers.Authorization; 'X-Lease-Token'=$claim.LeaseToken;
                            'X-Screenshot-Sha256'=(Get-FileHash -LiteralPath $screenshot -Algorithm SHA256).Hash.ToLowerInvariant() }
        if (-not $claim.ScreenshotUploadUrl.StartsWith('/api/agent/stage2/')) { throw 'Invalid screenshot route.' }
        try {
            Invoke-WebRequest -Uri ($apiRoot+$claim.ScreenshotUploadUrl) -Method Put -Headers $uploadHeaders -InFile $screenshot -ContentType 'image/png' -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 60 | Out-Null
        } catch { throw 'Screenshot upload failed. Preserve the journal and retry Publish; do not rerun the desktop flow.' }
    }
    $result=Invoke-WorkerApi 'POST' $claim.ResultUrl @{
        lease_token=$claim.LeaseToken; SubmissionStatus=[string]$outputs.SubmissionStatus
    }
    if ($outputs.SubmissionStatus -eq 'SUBMITTED_WAITING_FOR_CONFIRMATION') {
        if ($result.Status -ne 'SUBMITTED_WAITING_FOR_CONFIRMATION' -or $result.SubmissionEnabled -ne $true) {
            throw 'Server did not acknowledge live submission. Preserve journal for reporting recovery.'
        }
        $journal.Phase='ArchivePending'; Write-Journal $journal
        Complete-Archive | ConvertTo-Json -Depth 5
        return
    }
    $journal.Phase='Completed';Write-Journal $journal
    Save-SubmissionReceipt $journal
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
