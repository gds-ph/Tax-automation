# Offline synthetic fixture; never starts PAD or submits a return.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Test-0619EPreparedXml.ps1')
$fixtureInputs = [pscustomobject]@{
    TIN1='000'; TIN2='000'; TIN3='000'; TIN4='00000'; FilingMonth='10'; FilingYear='2026'
    RegisteredName='SYNTHETIC TEST'; RDOCode='047'; EmailAddress='test@example.invalid'
}
$fixture = @'
<div>frm0619E:txtTIN1=000frm0619E:txtTIN1=</div>
<div>frm0619E:txtTIN2=000frm0619E:txtTIN2=</div>
<div>frm0619E:txtTIN3=000frm0619E:txtTIN3=</div>
<div>frm0619E:txtBranchCode=00000frm0619E:txtBranchCode=</div>
<div>frm0619E:txtMonth=10frm0619E:txtMonth=</div>
<div>frm0619E:txtYear=2026frm0619E:txtYear=</div>
<div>frm0619E:txtTaxpayerName=SYNTHETIC TESTfrm0619E:txtTaxpayerName=</div>
<div>frm0619E:txtRDOCode=047frm0619E:txtRDOCode=</div>
<div>txtEmail=test@example.invalidtxtEmail=</div>
<div>frm0619E:optAmend:N=truefrm0619E:optAmend:N=</div>
<div>frm0619E:optAmend:Y=falsefrm0619E:optAmend:Y=</div>
<div>frm0619E:optWithheld:N=truefrm0619E:optWithheld:N=</div>
<div>frm0619E:optWithheld:Y=falsefrm0619E:optWithheld:Y=</div>
<div>frm0619E:optCategory:P=truefrm0619E:optCategory:P=</div>
<div>frm0619E:optCategory:G=falsefrm0619E:optCategory:G=</div>
<div>frm0619E:txtAtc=WME10frm0619E:txtAtc=</div>
<div>frm0619E:txtTaxTypeCode=WEfrm0619E:txtTaxTypeCode=</div>
<div>txtFinalFlag=0txtFinalFlag=</div>
'@
foreach ($number in @('14','15','16','17A','17B','17C','17D','18')) {
    $fixture += "<div>frm0619E:txtTax$number=0.00frm0619E:txtTax$number=</div>"
}
$fixturePath = [IO.Path]::GetTempFileName()
function Check-Fixture([string]$Label, [string]$Xml, [bool]$Retry, [bool]$Expected) {
    [IO.File]::WriteAllText($fixturePath, $Xml)
    $accepted = $true
    try { Assert-0619EPreparedXml -Path $fixturePath -Inputs $fixtureInputs -AllowFailedSubmissionRetry:$Retry }
    catch { $accepted = $false }
    if ($accepted -ne $Expected) { throw "Failed: $Label" }
    Write-Output "PASS: $Label"
}
try {
    Check-Fixture 'fresh preparation' $fixture $false $true
    $failed = $fixture.Replace('txtFinalFlag=0txtFinalFlag=', 'txtFinalFlag=2txtFinalFlag=')
    Check-Fixture 'failed transmission blocked in preparation' $failed $false $false
    Check-Fixture 'failed transmission accepted for approved retry' $failed $true $true
    foreach ($flag in @('1','3')) {
        Check-Fixture "flag $flag blocked even for retry" ($fixture.Replace('txtFinalFlag=0txtFinalFlag=', "txtFinalFlag=${flag}txtFinalFlag=")) $true $false
    }
    Check-Fixture 'duplicate flag blocked' ($failed + '<div>txtFinalFlag=2txtFinalFlag=</div>') $true $false
    Check-Fixture 'missing flag blocked' ($failed.Replace('<div>txtFinalFlag=2txtFinalFlag=</div>', '')) $true $false
    Check-Fixture 'changed amount blocked' ($failed.Replace('txtTax14=0.00', 'txtTax14=1.00')) $true $false
    Check-Fixture 'changed identity blocked' ($failed.Replace('SYNTHETIC TEST', 'OTHER TEST')) $true $false
} finally { Remove-Item -LiteralPath $fixturePath }
