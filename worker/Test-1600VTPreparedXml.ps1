# Verify the original private-agent zero-filing contract before publishing.
function Assert-1600VTPreparedXml {
    param([string]$Path, $Inputs)
    $file = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($file.Length -gt 1MB) { throw '1600VT XML exceeds the expected size.' }
    $text = [IO.File]::ReadAllText($file.FullName)
    $expected = @{
        'frm1600VT:txtPg1I1Month'=[string]$Inputs.FilingMonth
        'frm1600VT:txtPg1I1Year'=([string]$Inputs.FilingYear).Substring(2,2)
        'frm1600VT:txtPg1TIN1'=[string]$Inputs.TIN1
        'frm1600VT:txtPg1TIN2'=[string]$Inputs.TIN2
        'frm1600VT:txtPg1TIN3'=[string]$Inputs.TIN3
        'frm1600VT:txtPg1TIN4'=[string]$Inputs.TIN4
        'frm1600VT:txtPg1I6RDO'=[string]$Inputs.RDOCode
        # eBIRForms normalizes registered names to uppercase on save.
        'frm1600VT:txtPg1Pt1I7WithholdingAgentsName'=([string]$Inputs.RegisteredName).ToUpperInvariant()
        'frm1600VT:txtPg1Pt1I11Email'=[string]$Inputs.EmailAddress
        'frm1600VT:rdoPg1I2AmendedYes'='false'
        'frm1600VT:rdoPg1I2AmendedNo'='true'
        'frm1600VT:rdoPg1I3TaxWithheldYes'='false'
        'frm1600VT:rdoPg1I3TaxWithheldNo'='true'
        'frm1600VT:rdoPg1I10CategoryofWthholdAgentPriv'='true'
        'frm1600VT:rdoPg1I10CategoryofWthholdAgentGovt'='false'
        'frm1600VT:rdoPg1I12TaxReliefYes'='false'
        'frm1600VT:rdoPg1I12TaxReliefNo'='true'
        'frm1600VT:txtPg1Pt1I12TaxReliefSpec'=''
    }
    $numeric = @('frm1600VT:txtPg1I4NoOfSheets','txtFinalFlag','frm1600VT:txtTotalOtherTax')
    foreach ($field in @('18TotTaxWithheld','19TaxRemittedInRtrn','20OthrPymntsMade','21TotTaxPymntsMade','22TaxStillDueOverremit','23Surcharge','24Interest','25Compromise','26TotPenalties','27TotAmtStillDueOverremit')) { $numeric += 'frm1600VT:txtPg1P2I'+$field }
    foreach ($n in 1..5) {
        $expected['frm1600VT:txtAtcCd'+$n]=''
        $expected['frm1600VT:txtPg1P2TaxBase'+$n]=''
        $expected['frm1600VT:txtPg1P2TaxRate'+$n]=''
        $numeric += 'frm1600VT:txtPg1P2TaxWithheld'+$n
    }
    foreach ($key in $numeric) { $expected[$key]='0' }
    foreach ($key in $expected.Keys) {
        $escaped=[regex]::Escape($key)
        $found=[regex]::Matches($text, '<div>\s*'+$escaped+'=(.*?)'+$escaped+'=\s*</div>', [Text.RegularExpressions.RegexOptions]::Singleline)
        if ($found.Count -ne 1) { throw '1600VT XML has missing or duplicate verification fields.' }
        $value=[Uri]::UnescapeDataString($found[0].Groups[1].Value)
        if ($key -in $numeric) {
            $number=[decimal]0
            if (-not [decimal]::TryParse($value,[Globalization.NumberStyles]::Number,[Globalization.CultureInfo]::InvariantCulture,[ref]$number) -or $number -ne 0) { throw '1600VT zero-filing amount mismatch.' }
        } elseif ($value -cne $expected[$key]) { throw "1600VT XML differs from the requested value for $key." }
    }
}
