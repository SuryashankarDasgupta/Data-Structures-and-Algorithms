# Weekly news-calendar refresh: pulls this week's FOMC/NFP/CPI events, syncs them into the Pine script,
# shows the next events and appends everything to logs/news_update.log. Never commits or pushes.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\update_news.ps1
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"     # the project venv (python -m venv .venv)
if (-not (Test-Path $py)) { throw "venv not found at $py - run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "news_update.log"

Push-Location $root
try {
    $lines = @("===== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')")
    foreach ($cmd in @("update", "pine", "")) {
        $lines += "> python -m bridge.news $cmd".TrimEnd()
        $cmdArgs = @("-m", "bridge.news")
        if ($cmd) { $cmdArgs += $cmd }
        $lines += (& $py @cmdArgs 2>&1 | ForEach-Object { "$_" })
    }
    $git = Get-Command git -ErrorAction SilentlyContinue
    $gitExe = if ($git) { $git.Source } else { "C:\Program Files\Git\cmd\git.exe" }
    $changed = & $gitExe status --porcelain -- data/high_impact_usd.csv pine/xauusd_daily_trend.pine
    if ($changed) {
        $lines += "CALENDAR CHANGED - commit and re-paste the Pine script into TradingView"
        $lines += $changed
    } else {
        $lines += "calendar unchanged"
    }
    $lines | Tee-Object -FilePath $log -Append
} finally {
    Pop-Location
}
