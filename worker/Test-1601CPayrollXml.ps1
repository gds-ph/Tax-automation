function Assert-1601CPayrollXml {
    param([string]$Path, $Inputs)
    $file = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($file.Length -gt 1MB) { throw '1601C XML exceeds expected size.' }
    $text = [IO.File]::ReadAllText($file.FullName)
    $p = $Inputs.Payroll
    $t = $Inputs.PayrollTotals
    if ($null -eq $p -or $p.schema -cne '1601c-payroll-v1' -or $p.payroll_confirmed -ne $true) { throw 'Missing reviewed payroll data.' }
    $expected = @{
        'frm1601c:txtTIN1'=[string]$Inputs.TIN1; 'frm1601c:txtTIN2'=[string]$Inputs.TIN2
        'frm1601c:txtTIN3'=[string]$Inputs.TIN3; 'frm1601c:txtBranchCode'=[string]$Inputs.TIN4
        'frm1601c:txtMonth'=[string]$Inputs.FilingMonth; 'frm1601c:txtYear'=[string]$Inputs.FilingYear
        'frm1601c:txtRDOCode'=[string]$Inputs.RDOCode
        'frm1601c:txtTaxpayerName'=[string]$Inputs.RegisteredName
        'frm1601c:txtAddress'=[string]$Inputs.RegisteredAddress
        'frm1601c:txtZipCode'=[string]$Inputs.ZipCode
        'txtEmail'=[string]$Inputs.EmailAddress
        'frm1601c:AmendedRtn_1'='false'; 'frm1601c:AmendedRtn_2'='true'
        'frm1601c:CatAgent_P'='true'; 'frm1601c:CatAgent_G'='false'
        'frm1601c:SpecialTax_1'='false'; 'frm1601c:SpecialTax_2'='true'
        'frm1601c:txtSheets'='0'; 'frm1601c:txtATC'='WW010'
        'frm1601c:TaxWithheld_1'=([decimal]$p.withheld -gt 0).ToString().ToLowerInvariant()
        'frm1601c:TaxWithheld_2'=([decimal]$p.withheld -eq 0).ToString().ToLowerInvariant()
        'frm1601c:txt20Other'=[string]$p.other_exempt_description
    }
    $amounts=@{14=$p.compensation;15=$p.minimum_wage;16=$p.mwe_benefits;17=$p.benefits;18=$p.de_minimis;
        19=$p.contributions;20=$p.other_exempt;21=$t.exempt;22=$t.taxable;23=$p.below_threshold;24=$t.subject;
        25=$p.withheld;26='0.00';27=$p.withheld;28='0.00';29='0.00';30='0.00';31=$p.withheld;
        32='0.00';33='0.00';34='0.00';35='0.00';36=$t.due}
    foreach ($item in $amounts.Keys) { $expected['frm1601c:txtTax'+$item]=[string]$amounts[$item] }
    foreach ($key in $expected.Keys) {
        $escaped=[regex]::Escape($key)
        $found=[regex]::Matches($text, '<div>\s*'+$escaped+'=(.*?)'+$escaped+'=\s*</div>', [Text.RegularExpressions.RegexOptions]::Singleline)
        if ($found.Count -ne 1) { throw "Missing or duplicate 1601C field: $key" }
        $value=[Uri]::UnescapeDataString($found[0].Groups[1].Value)
        if ($key -match ':txtTax\d+$') { $value=$value.Replace(',','') }
        if ($value -ine $expected[$key]) { throw "1601C payroll mismatch at $key. Do not publish or submit." }
    }
}
