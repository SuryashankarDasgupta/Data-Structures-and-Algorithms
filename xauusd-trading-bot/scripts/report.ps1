# Daily bridge report (realized P&L, orders, rejected alerts) from runtime\journal.sqlite3, optionally with the
# running bridge's /status.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\report.ps1                 # today (UTC)
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\report.ps1 -Yesterday      # yesterday (UTC)
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\report.ps1 -Date 2026-11-05 -Status
#
# Dates are UTC days because the bridge journals by UTC day. In India (UTC+5:30) the daily-close alerts arrive
# around 03:30 IST, which is still the previous UTC day, so use -Yesterday in the morning.
param(
    [string]$Date,
    [switch]$Yesterday,
    [switch]$Status
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv not found at $py - run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }

if (-not $Date) {
    $utc = [DateTime]::UtcNow
    if ($Yesterday) { $utc = $utc.AddDays(-1) }
    $Date = $utc.ToString("yyyy-MM-dd")
}
if ($Date -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "-Date must be YYYY-MM-DD" }

$env:JOURNAL_PATH = Join-Path $root "runtime\journal.sqlite3"
if (-not (Test-Path $env:JOURNAL_PATH)) {
    Write-Host "No journal yet at $env:JOURNAL_PATH (the bridge creates it on first start)."
} else {
    Push-Location $root
    try { & $py -m bridge.report $Date } finally { Pop-Location }
}

if ($Status) {
    # Only BRIDGE_PORT is read from .env; nothing else (the secret is never touched).
    $port = 8080
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        $line = Select-String -Path $envFile -Pattern '^\s*BRIDGE_PORT\s*=\s*(\d+)' | Select-Object -First 1
        if ($line) { $port = [int]$line.Matches[0].Groups[1].Value }
    }
    Write-Host ""
    Write-Host "=== bridge status (http://127.0.0.1:$port/status) ==="
    try {
        $s = Invoke-RestMethod -Uri "http://127.0.0.1:$port/status" -TimeoutSec 5
    } catch {
        Write-Host "Bridge is not running (nothing answered on port $port). Start it with scripts\start_bridge.ps1"
        exit 1
    }
    $pos = if ($s.position) { "$($s.position.units) oz @ $($s.position.avg_price), stop $($s.position.stop_loss)" } else { "flat" }
    [pscustomobject]@{
        Broker         = $s.broker
        Balance        = $s.balance
        Position       = $pos
        EntriesToday   = $s.entries_today
        ExecutionMode  = if ($s.execution_mode) { $s.execution_mode } else { "sync (older bridge)" }
        QueueDepth     = $s.queue_depth
        NextNews       = ($s.next_news -join "; ")
        CalendarStale  = $s.news_calendar_stale
    } | Format-List
    if ($s.recent_results) {
        Write-Host "Recent results:"
        $s.recent_results | Format-Table time, status, key, detail -AutoSize -Wrap
    }
}
