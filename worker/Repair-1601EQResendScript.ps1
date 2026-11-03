[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$FormPath)
$ErrorActionPreference='Stop'
$resolved=(Resolve-Path -LiteralPath $FormPath).Path
if([IO.Path]::GetFileName($resolved) -cne 'BIR-Form1601EQ.hta'){throw 'Only the 1601EQ application script is supported.'}
$originalHash='CD56BF18D1DA2127D578AF611FE8005FE49913A65781BB603B22B31BBE548B96'
$encoding=[Text.Encoding]::GetEncoding(28591)
$bytes=[IO.File]::ReadAllBytes($resolved)
$source=$encoding.GetString($bytes)
$hash=(Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
if($hash -ne $originalHash){
    $reversed=$source.Replace('            reSendEmail();  ','            emailResend();  ')
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$reverseHash=[BitConverter]::ToString($sha.ComputeHash($encoding.GetBytes($reversed))).Replace('-','')}finally{$sha.Dispose()}
    if($reverseHash -eq $originalHash){Write-Output 'ALREADY_PATCHED';return}
    throw 'Unrecognized script hash. No changes made.'
}
if(([regex]::Matches($source,'\bemailResend\(\);')).Count -ne 1){throw 'Expected exactly one defective call.'}
$patched=$source.Replace('emailResend();','reSendEmail();')
$backup=$resolved+'.before-resend-fix.bak'
if(Test-Path -LiteralPath $backup){
    if((Get-FileHash -LiteralPath $backup -Algorithm SHA256).Hash -ne $originalHash){throw 'Existing backup does not match; refusing overwrite.'}
}else{[IO.File]::WriteAllBytes($backup,$bytes)}
[IO.File]::WriteAllBytes($resolved,$encoding.GetBytes($patched))
if([IO.File]::ReadAllText($resolved,$encoding) -cne $patched){throw 'Patch verification failed.'}
Write-Output 'PATCHED'
