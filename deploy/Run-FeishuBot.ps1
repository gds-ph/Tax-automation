# Keeps the Feishu assistant running on this PC and restarts it if it exits.
# Started at Windows sign-in by Install-FeishuBotTask.ps1; it must run as the user signed in to Claude Code.
# Output goes to logs\feishu-bot.log with connection tickets and keys masked.
$ErrorActionPreference = 'Continue'
# A stray Ctrl+C/console signal once ended the whole loop (exit 0xC000013A); now only the bot exits and restarts.
try { [Console]::TreatControlCAsInput = $true } catch { }
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir 'feishu-bot.log'

while ($true) {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 5MB) {
        Move-Item $log "$log.old" -Force
    }
    # Shared write so the log can be read while the bot runs (Add-Content locks it).
    $stream = [IO.File]::Open($log, 'Append', 'Write', 'ReadWrite')
    $writer = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
    $writer.AutoFlush = $true
    try {
        $writer.WriteLine("$(Get-Date -Format s) starting Feishu assistant")
        & $python -u (Join-Path $root 'manage.py') run_feishu_bot 2>&1 |
            ForEach-Object { $writer.WriteLine(("$_" -replace '(ticket|access_key|token|secret)=[^&\s]*', '$1=***')) }
        $writer.WriteLine("$(Get-Date -Format s) Feishu assistant exited (code $LASTEXITCODE); restarting in 30 seconds")
    } finally {
        $writer.Close()
    }
    Start-Sleep -Seconds 30
}
