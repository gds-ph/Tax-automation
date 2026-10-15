function Assert-0619EPreparedXml {
    param([string]$Path, $Inputs)
    $file = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($file.Length -gt 1MB) { throw '0619E XML exceeds the expected size.' }
    $text = [IO.File]::ReadAllText($file.FullName)
    $expected = @{
        'frm0619E:txtTIN1'=[string]$Inputs.TIN1; 'frm0619E:txtTIN2'=[string]$Inputs.TIN2
        'frm0619E:txtTIN3'=[string]$Inputs.TIN3; 'frm0619E:txtBranchCode'=[string]$Inputs.TIN4
        'frm0619E:txtMonth'=[string]$Inputs.FilingMonth; 'frm0619E:txtYear'=[string]$Inputs.FilingYear
        'frm0619E:txtTaxpayerName'=[string]$Inputs.RegisteredName; 'frm0619E:txtRDOCode'=[string]$Inputs.RDOCode
        'txtEmail'=[string]$Inputs.EmailAddress
        'frm0619E:optAmend:N'='true'; 'frm0619E:optAmend:Y'='false'
        'frm0619E:optWithheld:N'='true'; 'frm0619E:optWithheld:Y'='false'
        'frm0619E:optCategory:P'='true'; 'frm0619E:optCategory:G'='false'
        'frm0619E:txtAtc'='WME10'; 'frm0619E:txtTaxTypeCode'='WE'; 'txtFinalFlag'='0'
    }
    foreach ($field in @('14','15','16','17A','17B','17C','17D','18')) { $expected['frm0619E:txtTax'+$field]='0.00' }
    $numericFields = @('14','15','16','17A','17B','17C','17D','18') | ForEach-Object { 'frm0619E:txtTax'+$_ }
    if ($null -ne $Inputs.SupplierSchedule) {
        if ($Inputs.SupplierSchedule.schema -cne '0619e-suppliers-v1' -or $Inputs.SupplierSchedule.schedule_confirmed -ne $true) { throw '0619E supplier review is missing.' }
        $amount = [decimal]::Parse([string]$Inputs.WithholdingTotal, [Globalization.CultureInfo]::InvariantCulture)
        if ($amount -le 0 -or $amount -gt 999999999.99) { throw 'Invalid 0619E withholding total.' }
        $sum = [decimal]0
        foreach ($row in $Inputs.SupplierSchedule.rows) { $sum += [decimal]::Parse([string]$row.tax, [Globalization.CultureInfo]::InvariantCulture) }
        if ($sum -ne $amount) { throw '0619E supplier total does not reconcile.' }
        $expected['frm0619E:optWithheld:N']='false'; $expected['frm0619E:optWithheld:Y']='true'
        foreach ($field in @('14','16','18')) { $expected['frm0619E:txtTax'+$field]=$amount.ToString('0.00', [Globalization.CultureInfo]::InvariantCulture) }
    }
    foreach ($key in $expected.Keys) {
        $escaped=[regex]::Escape($key)
        $matchesFound=[regex]::Matches($text, '<div>\s*'+$escaped+'=(.*?)'+$escaped+'=\s*</div>', [Text.RegularExpressions.RegexOptions]::Singleline)
        if ($matchesFound.Count -ne 1) { throw '0619E XML has missing or duplicate verification fields.' }
        $value=[Uri]::UnescapeDataString($matchesFound[0].Groups[1].Value)
        if ($key -in $numericFields) { $value=$value.Replace(',', '') }
        if ($value -cne $expected[$key]) { throw '0619E XML does not match the approved return amounts and identity. Do not publish or submit it.' }
    }
}
