$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (Get-NetTCPConnection -LocalPort 8443 -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8443 already has a listener. Do not start another proxy.'
}
if (!(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue)) {
    throw 'Start the Django dashboard on 127.0.0.1:8001 first.'
}
$executable = Join-Path $projectRoot 'tools\caddy\caddy.exe'
& $executable validate --config deploy\Caddyfile --adapter caddyfile
if ($LASTEXITCODE -ne 0) { throw 'Invalid HTTPS configuration.' }
$process = Start-Process -FilePath $executable -ArgumentList 'run --config deploy\Caddyfile --adapter caddyfile' -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput logs\caddy-stdout.log -RedirectStandardError logs\caddy-stderr.log
Write-Output "Started worker HTTPS proxy, process $($process.Id). Check logs\caddy-stderr.log if connection fails."
