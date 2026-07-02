# ============================================================
#  Confirmed Pullback Swing — Headless Runner (Windows)
#  Runs every 15 min via Task Scheduler.
#  Checks market hours, then calls Claude CLI with the
#  full agentic strategy prompt. Logs all output.
# ============================================================

param(
    [string]$LogDir = "$env:USERPROFILE\SwingScreener\logs"
)

# ── Config ────────────────────────────────────────────────
$PROMPT  = "Start the 15-minute Confirmed Pullback Swing routine on Agentic 2 now"
$TIMEOUT = 600   # seconds — max time Claude is allowed to run per cycle

# ── Logging ───────────────────────────────────────────────
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$stamp   = Get-Date -Format "yyyyMMdd_HHmm"
$logFile = Join-Path $LogDir "cycle_$stamp.log"

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

Log "=== Swing Screener Cycle Start ==="

# ── Market hours check (CDT = UTC-5) ──────────────────────
$utcNow      = [DateTime]::UtcNow
$cstOffset   = [TimeSpan]::FromHours(-6)          # CST (UTC-6); change to -5 for CDT (summer)
$cstNow      = $utcNow.Add($cstOffset)
$dayOfWeek   = $cstNow.DayOfWeek
$marketOpen  = [TimeSpan]"08:30:00"              # 9:30 AM ET = 8:30 AM CST
$marketClose = [TimeSpan]"15:00:00"              # 4:00 PM ET = 3:00 PM CST
$isWeekday   = $dayOfWeek -ne "Saturday" -and $dayOfWeek -ne "Sunday"
$isMarketHrs = $cstNow.TimeOfDay -ge $marketOpen -and $cstNow.TimeOfDay -le $marketClose

Log "CST now: $($cstNow.ToString('ddd yyyy-MM-dd HH:mm')) | Weekday: $isWeekday | Market hours: $isMarketHrs"

if (-not $isWeekday) {
    Log "Weekend — skipping cycle."
    exit 0
}

if (-not $isMarketHrs) {
    Log "Outside market hours (8:30 AM–3:00 PM CST) — skipping cycle."
    exit 0
}

# ── Verify Claude CLI is installed ────────────────────────
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Log "ERROR: 'claude' command not found. Run: npm install -g @anthropic-ai/claude-code"
    exit 1
}
Log "Claude CLI found: $($claudeCmd.Source)"

# ── Verify API key is set ─────────────────────────────────
if (-not $env:ANTHROPIC_API_KEY) {
    Log "ERROR: ANTHROPIC_API_KEY not set. Add it to System Environment Variables."
    exit 1
}
Log "API key: present (length $($env:ANTHROPIC_API_KEY.Length))"

# ── Run Claude ─────────────────────────────────────────────
Log "Launching Claude with agentic strategy prompt..."
Log "--- Claude output start ---"

$proc = Start-Process -FilePath "claude" `
    -ArgumentList @(
        "--dangerously-skip-permissions",
        "-p", "`"$PROMPT`""
    ) `
    -NoNewWindow `
    -PassThru `
    -RedirectStandardOutput "$logFile.stdout" `
    -RedirectStandardError  "$logFile.stderr"

# Wait up to $TIMEOUT seconds
$finished = $proc.WaitForExit($TIMEOUT * 1000)
if (-not $finished) {
    Log "TIMEOUT after ${TIMEOUT}s — killing Claude process."
    $proc.Kill()
    exit 2
}

# Append stdout/stderr to main log
if (Test-Path "$logFile.stdout") {
    Get-Content "$logFile.stdout" | ForEach-Object { Add-Content $logFile "  $_" }
    Remove-Item "$logFile.stdout"
}
if (Test-Path "$logFile.stderr") {
    $errContent = Get-Content "$logFile.stderr" -Raw
    if ($errContent) { Add-Content $logFile "  [STDERR] $errContent" }
    Remove-Item "$logFile.stderr"
}

Log "--- Claude output end ---"
Log "Exit code: $($proc.ExitCode)"
Log "=== Cycle complete ==="

# ── Rotate old logs (keep last 7 days) ────────────────────
Get-ChildItem $LogDir -Filter "cycle_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force
