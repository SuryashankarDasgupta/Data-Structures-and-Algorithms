# Start the webhook bridge with settings from .env. Journal, paper account state and the kill switch
# live under runtime/ (gitignored). Stop with Ctrl+C.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_bridge.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "venv not found at $py - run: python -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw ".env not found - copy .env.example to .env and set WEBHOOK_SECRET" }

# KEY=VALUE lines; blank lines, comments and trailing "# ..." are ignored
foreach ($line in Get-Content $envFile) {
    $line = ($line -replace '\s+#.*$', '').Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { continue }
    $key, $value = $line.Split("=", 2)
    [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim().Trim('"').Trim("'"), "Process")
}

$runtime = Join-Path $root "runtime"
New-Item -ItemType Directory -Force $runtime | Out-Null
$env:JOURNAL_PATH = Join-Path $runtime "journal.sqlite3"
$env:PAPER_STATE_FILE = Join-Path $runtime "paper_state.json"
$env:KILL_SWITCH_FILE = Join-Path $runtime "KILL_SWITCH"
if ($env:BROKER -and $env:BROKER -ne "paper") { Write-Warning "BROKER=$($env:BROKER) - this is NOT paper trading" }

Push-Location $root
try {
    & $py -m bridge.server
} finally {
    Pop-Location
}
