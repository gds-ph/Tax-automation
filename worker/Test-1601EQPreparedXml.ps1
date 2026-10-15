function Assert-1601EQPreparedXml {
    param([string]$Path, $Inputs)
    if ((Get-Item -LiteralPath $Path).Length -gt 1MB) { throw '1601EQ XML exceeds expected size.' }
    $text = [IO.File]::ReadAllText($Path)
    function Read-EQField([string]$Key) {
        $k=[regex]::Escape($Key)
        $m=[regex]::Matches($text, '<div>\s*'+$k+'=(.*?)'+$k+'=\s*</div>', [Text.RegularExpressions.RegexOptions]::Singleline)
        if ($m.Count -ne 1) { throw "Missing or duplicate 1601EQ field: $Key" }
        return [Uri]::UnescapeDataString($m[0].Groups[1].Value)
    }
    function Assert-EQMoney([string]$Key, [string]$Expected) {
        $actual=(Read-EQField $Key).Replace(',', '')
        if (-not $actual) { $actual='0' }
        $culture=[Globalization.CultureInfo]::InvariantCulture
        if ([decimal]::Parse($actual,$culture) -ne [decimal]::Parse($Expected,$culture)) { throw "1601EQ amount mismatch: $Key" }
    }
    $s=$Inputs.QuarterlySchedule; $t=$Inputs.QuarterlyTotals
    if ($s.schema -cne '1601eq-suppliers-v1' -or $s.schedule_confirmed -ne $true -or [string]$s.quarter -cne [string]$Inputs.FilingQuarter) { throw 'Quarterly review is missing or period differs.' }
    $expected=@{'txtYear'=[string]$Inputs.FilingYear; 'txtTIN1'=[string]$Inputs.TIN1; 'txtTIN2'=[string]$Inputs.TIN2; 'txtTIN3'=[string]$Inputs.TIN3; 'txtBranchCode'=[string]$Inputs.TIN4; 'txtRDOCode'=[string]$Inputs.RDOCode; 'txtTaxpayerName'=([string]$Inputs.RegisteredName).ToUpperInvariant(); 'optAmend:Y'='false'; 'optAmend:N'='true'; 'optWithheld:Y'='true'; 'optWithheld:N'='false'; 'optCategory:P'='true'; 'optCategory:G'='false'; 'ifRefund'='false'; 'ifIssueCert'='false'; 'ifCarriedOver'='false'}
    foreach ($i in 1..4) { $expected['optQuarter:'+$i]=([string]$i -ceq [string]$Inputs.FilingQuarter).ToString().ToLowerInvariant() }
    foreach ($key in $expected.Keys) { if ((Read-EQField ('frm1601EQ:'+$key)) -cne $expected[$key]) { throw "1601EQ identity/scope mismatch: $key" } }
    if ((Read-EQField 'txtEmail') -cne [string]$Inputs.EmailAddress) { throw '1601EQ email mismatch.' }
    $seen=@{}
    foreach ($i in 1..6) {
        $atc=Read-EQField ('frm1601EQ:txtAtcCd'+$i)
        if ($atc) {
            $group=@($t.groups | Where-Object { $_.atc -ceq $atc })
            if ($group.Count -ne 1 -or $seen.ContainsKey($atc)) { throw 'Unexpected or duplicate quarterly ATC.' }
            $seen[$atc]=$true
            Assert-EQMoney ('frm1601EQ:txtTaxBase'+$i) $group[0].base
            Assert-EQMoney ('frm1601EQ:txtTaxRate'+$i) $group[0].rate
            Assert-EQMoney ('frm1601EQ:txtTaxbeWithHeld'+$i) $group[0].tax
        } else {
            foreach ($field in @('txtTaxBase','txtTaxRate','txtTaxbeWithHeld')) { Assert-EQMoney ('frm1601EQ:'+$field+$i) '0' }
        }
    }
    if ($seen.Count -ne @($t.groups).Count) { throw 'Quarterly ATC is missing.' }
    $amounts=@{'19'=$t.withheld; '20'=$t.first_remittance; '21'=$t.second_remittance; '22'='0'; '23'='0'; '24'=$t.remittances; '25'=$t.tax_due; '26'=$t.surcharge; '27'=$t.interest; '28'=$t.compromise; '29'=$t.penalties; '30'=$t.due}
    foreach ($key in $amounts.Keys) { Assert-EQMoney ('frm1601EQ:txtTax'+$key) $amounts[$key] }
    Assert-EQMoney 'frm1601EQ:txtTotalOtherTax' '0'
    Assert-EQMoney 'frm1601EQ:txtNoSheets' '0'
}
