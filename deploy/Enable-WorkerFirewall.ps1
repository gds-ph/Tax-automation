# Run in Administrator PowerShell on the DASHBOARD HOST.
$ErrorActionPreference = 'Stop'
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell as Administrator on the dashboard host, then run this script.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $projectRoot 'tools\caddy\caddy.exe'
if (!(Test-Path -LiteralPath $executable)) { throw 'Local Caddy executable is missing.' }
if (!(Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -eq '192.168.8.148'})) {
    throw 'The dashboard host address has changed; review the configuration first.'
}
$ruleName = 'eBIR-Worker-HTTPS-8443'
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    throw 'This firewall rule already exists. Inspect it before making changes.'
}
New-NetFirewallRule -Name $ruleName -DisplayName 'eBIR worker HTTPS from automation VM only' -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalAddress 192.168.8.148 -LocalPort 8443 -RemoteAddress 192.168.14.135 -Program $executable -Profile Domain -EdgeTraversalPolicy Block
# Rollback: Remove-NetFirewallRule -Name 'eBIR-Worker-HTTPS-8443'
