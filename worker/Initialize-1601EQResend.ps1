[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$ApprovedXmlPath)
$ErrorActionPreference='Stop'
try {
    $xml=(Resolve-Path -LiteralPath $ApprovedXmlPath).Path
    if([IO.Path]::GetDirectoryName($xml) -ine 'C:\eBIRForms\savefile' -or [IO.Path]::GetFileName($xml) -notmatch '^\d+-1601EQ-\d{4}Q[1-4]\.xml$'){throw 'Unexpected return path.'}
    $text=[IO.File]::ReadAllText($xml)
    $flags=[regex]::Matches($text,'txtFinalFlag=([0-3])txtFinalFlag=')
    if($flags.Count -ne 1){throw 'Missing or ambiguous saved status.'}
    $flag=$flags[0].Groups[1].Value
    if($flag -eq '1'){throw 'Return is already marked submitted.'}
    $roots=@(Get-CimInstance Win32_Process -Filter "Name='mshta.exe'" | ForEach-Object {
        if($_.CommandLine -match '"([^"\r\n]+\\BIRForms\.hta)"') {[IO.Path]::GetDirectoryName($Matches[1])}
    } | Sort-Object -Unique)
    if($roots.Count -ne 1){throw 'Expected one eBIRForms instance.'}
    $root=[IO.Path]::GetFullPath($roots[0])
    $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if(-not $root.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected runtime directory.'}
    $form=Join-Path $root 'forms\BIR-Form1601EQ.hta'
    $util=Join-Path $root 'js\string-util.js'
    if([IO.File]::ReadAllText($util) -notmatch 'function reSendEmail\(\)'){throw 'Resend implementation unavailable.'}
    if($flag -eq '2') {
        & (Join-Path $PSScriptRoot 'Repair-1601EQResendScript.ps1') -FormPath $form | Out-Null
        Write-Output 'RESEND'
    } else { Write-Output 'NORMAL' }
} catch { Write-Output 'BLOCKED' }
