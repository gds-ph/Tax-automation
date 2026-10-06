# Called by WorkerBridge under its shared worker mutex, before claiming desktop work.
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ConfigPath,
      [string]$SaveFolder='C:\eBIRForms\savefile',
      [string]$ArchiveRoot='C:\TaxAutomation\Archive\Cancelled')
$ErrorActionPreference='Stop'
$workerFolder=Split-Path -Parent ([IO.Path]::GetFullPath($ConfigPath))
foreach ($name in @('journal.json','stage2-journal.json')) {
    $path=Join-Path $workerFolder $name
    if (Test-Path -LiteralPath $path) {
        $j=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        if ($j.Phase -notin @('Completed','Requesting')) { return }
    }
}
# Do not move a saved return while an eBIRForms form may be open.
if (Get-Process mshta -ErrorAction SilentlyContinue) { return }
$config=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$base=([string]$config.ApiBaseUrl).TrimEnd('/')
$uri=[Uri]$base
if ($uri.UserInfo -or $uri.Query -or $uri.Fragment -or $uri.AbsolutePath -ne '/' -or
    ($uri.Scheme -ne 'https' -and -not ($uri.Scheme -eq 'http' -and $uri.Host -in @('localhost','127.0.0.1')))) {
    throw 'Invalid worker API URL.'
}
function Api([string]$Route,$Body) {
    if (Get-Command Invoke-WorkerApi -CommandType Function -ErrorAction SilentlyContinue) {
        # Preserve the parent bridge's transient-network retry classification.
        return (Invoke-WorkerApi 'POST' $Route $Body)
    }
    try {
        $r=Invoke-WebRequest -Uri ($base+$Route) -Method Post -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 60 `
            -Headers @{Authorization=('Bearer '+[string]$config.Token)} -ContentType 'application/json' `
            -Body ($Body | ConvertTo-Json -Compress)
        if ($r.StatusCode -eq 204) { return $null }
        $content=$r.Content
        if ($content -is [byte[]]) { $content=[Text.Encoding]::UTF8.GetString($content) }
        return ($content | ConvertFrom-Json)
    } catch { throw 'Cancellation cleanup API failed. Preserve files and restart the parent worker to retry reporting.' }
}
function NoLinks([string]$Path) {
    $cursor=$Path
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and
            ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Links and junctions are not allowed in cleanup paths.'
        }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
}
$job=Api '/api/agent/cancellation/claim/' @{}
if ($null -eq $job) { return }
if (-not $job.CleanupId) { throw 'Invalid cleanup response.' }
$id=([guid]$job.CleanupId).ToString()
$result=@{Archived=$false; ArchivePath=''; Sha256=''; Error=''}
$handle=$null
try {
    $order=[string]$job.WorkOrderId
    if ($order -notmatch '^WO-[A-Za-z0-9-]+$') { throw 'Invalid work order.' }
    $source=[IO.Path]::GetFullPath([string]$job.Source)
    $saveRoot=[IO.Path]::GetFullPath($SaveFolder).TrimEnd('\')
    $root=[IO.Path]::GetFullPath($ArchiveRoot).TrimEnd('\')
    $folder=[IO.Path]::GetFullPath((Join-Path $root $order))
    $dest=Join-Path $folder ([IO.Path]::GetFileName($source))
    $manifestPath=Join-Path $folder ($id+'.json')
    if ([IO.Path]::GetDirectoryName($source) -ine $saveRoot -or [IO.Path]::GetExtension($source) -ine '.xml' -or
        [IO.Path]::GetFileName($source) -cne [string]$job.Filename -or
        $dest -ine [IO.Path]::GetFullPath([string]$job.ArchivePath) -or
        -not $folder.StartsWith($root+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $folder -ieq $saveRoot -or $folder.StartsWith($saveRoot+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Cleanup paths do not match the cancelled filing.'
    }
    NoLinks $source; NoLinks $dest; NoLinks $manifestPath
    $manifest=$null
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest=Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.CleanupId -cne $id -or $manifest.Source -ine $source -or $manifest.ArchivePath -ine $dest) {
            throw 'Archive manifest does not match.'
        }
    }
    if (Test-Path -LiteralPath $source -PathType Leaf) {
        if ($manifest -and $manifest.State -eq 'Archived') { throw 'An XML reappeared after cleanup. Retain it for review.' }
        # Allow our rename, but deny writers while verifying and moving the file.
        $handle=[IO.File]::Open($source,'Open','Read',([IO.FileShare]::Read -bor [IO.FileShare]::Delete))
        $modified=(Get-Item -LiteralPath $source).LastWriteTimeUtc
        if ($modified -lt ([DateTimeOffset]::Parse($job.PreparedAfter).UtcDateTime).AddSeconds(-2) -or
            $modified -gt ([DateTimeOffset]::Parse($job.CancelledAt).UtcDateTime).AddSeconds(2)) {
            throw 'XML timestamp is outside this preparation and cancellation. Retain for review.'
        }
        $hasher=[Security.Cryptography.SHA256]::Create()
        try { $hash=[BitConverter]::ToString($hasher.ComputeHash($handle)).Replace('-','').ToLowerInvariant() }
        finally { $hasher.Dispose() }
        if ($manifest -and $manifest.Sha256 -cne $hash) { throw 'XML changed since cleanup started.' }
        if (Test-Path -LiteralPath $dest) { throw 'Destination already exists; no files overwritten.' }
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        $manifest=@{CleanupId=$id; WorkOrderId=$order; Source=$source; ArchivePath=$dest; Sha256=$hash; State='Moving'}
        [IO.File]::WriteAllText($manifestPath,($manifest | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
        # Exact-path rename, never recursive deletion or wildcard operations.
        [IO.File]::Move($source,$dest)
        $handle.Dispose(); $handle=$null
    } else {
        if (-not $manifest -or -not (Test-Path -LiteralPath $dest -PathType Leaf)) {
            throw 'XML missing without an archive manifest; operator review required.'
        }
        $hash=[string]$manifest.Sha256
    }
    if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant() -cne $hash) {
        throw 'Archive hash does not match.'
    }
    $manifest.State='Archived'
    [IO.File]::WriteAllText($manifestPath,($manifest | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    $result.Archived=$true; $result.ArchivePath=$dest; $result.Sha256=$hash
} catch {
    $result.Error='XML cleanup needs operator review. Inspect the cancellation archive and original file.'
} finally { if ($handle) { $handle.Dispose() } }
# A lost acknowledgement retries the same RUNNING job and verifies its archive manifest.
$null=Api ('/api/agent/cancellation/'+$id+'/result/') $result
