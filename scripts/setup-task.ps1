# ============================================================
#  ONE-TIME SETUP — Run this once as Administrator.
#  Creates a Windows Task Scheduler job that runs the
#  Confirmed Pullback Swing strategy every 15 minutes.
# ============================================================

#Requires -RunAsAdministrator

$TASK_NAME   = "SwingScreener-ConfirmedPullback"
$SCRIPT_PATH = "$env:USERPROFILE\SwingScreener\swing-screener.ps1"
$LOG_DIR     = "$env:USERPROFILE\SwingScreener\logs"
$INSTALL_DIR = "$env:USERPROFILE\SwingScreener"

Write-Host "`n=== Swing Screener Headless Setup ===" -ForegroundColor Cyan

# ── Step 1: Create install directory ─────────────────────
if (-not (Test-Path $INSTALL_DIR)) {
    New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null
    New-Item -ItemType Directory -Path $LOG_DIR     -Force | Out-Null
    Write-Host "Created: $INSTALL_DIR" -ForegroundColor Green
}

# ── Step 2: Copy script ───────────────────────────────────
$sourceScript = Join-Path $PSScriptRoot "swing-screener.ps1"
if (Test-Path $sourceScript) {
    Copy-Item $sourceScript -Destination $SCRIPT_PATH -Force
    Write-Host "Copied script to: $SCRIPT_PATH" -ForegroundColor Green
} else {
    Write-Host "ERROR: swing-screener.ps1 not found next to this script." -ForegroundColor Red
    exit 1
}

# ── Step 3: Set ANTHROPIC_API_KEY ─────────────────────────
$existingKey = [System.Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "Machine")
if (-not $existingKey) {
    $apiKey = Read-Host "Enter your ANTHROPIC_API_KEY (starts with sk-ant-)"
    if ($apiKey -match "^sk-ant-") {
        [System.Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $apiKey, "Machine")
        Write-Host "ANTHROPIC_API_KEY saved to System environment." -ForegroundColor Green
    } else {
        Write-Host "WARNING: Key format looks wrong. Set ANTHROPIC_API_KEY manually if needed." -ForegroundColor Yellow
    }
} else {
    Write-Host "ANTHROPIC_API_KEY already set (length $($existingKey.Length))." -ForegroundColor Green
}

# ── Step 4: Verify Claude CLI ─────────────────────────────
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claudeCmd) {
    Write-Host "`nInstalling Claude Code CLI..." -ForegroundColor Yellow
    npm install -g @anthropic-ai/claude-code
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: npm install failed. Install Node.js from https://nodejs.org first." -ForegroundColor Red
        exit 1
    }
}
Write-Host "Claude CLI: OK" -ForegroundColor Green

# ── Step 5: Register Task Scheduler job ───────────────────
# Remove old task if it exists
Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$SCRIPT_PATH`""

# Trigger: every 15 minutes, 8:15 AM–3:15 PM CST, Mon–Fri
# (starts 15 min early so the 8:30 AM cycle doesn't miss)
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "08:15AM"

# Repeat every 15 min for 7 hours (covers full market day 8:30–3:00 PM + buffer)
$trigger.RepetitionInterval = [TimeSpan]::FromMinutes(15)
$trigger.RepetitionDuration = [TimeSpan]::FromHours(7)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 12) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun $false

# Run as current user, only when logged on (avoids UAC issues with MCP)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TASK_NAME `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Confirmed Pullback Swing — Agentic 2 auto-trading (15-min cycle)" `
    -Force | Out-Null

Write-Host "Task Scheduler job registered: '$TASK_NAME'" -ForegroundColor Green

# ── Step 6: Verify MCP config ─────────────────────────────
$mcpConfig = "$env:APPDATA\Claude\claude_desktop_config.json"
$claudeConfig = "$env:USERPROFILE\.claude\settings.json"
Write-Host "`n--- MCP Config Check ---" -ForegroundColor Cyan
if (Test-Path $mcpConfig) {
    Write-Host "Found Claude Desktop config: $mcpConfig" -ForegroundColor Green
    $cfg = Get-Content $mcpConfig -Raw | ConvertFrom-Json
    if ($cfg.mcpServers) {
        Write-Host "MCP servers configured: $($cfg.mcpServers.PSObject.Properties.Name -join ', ')" -ForegroundColor Green
    } else {
        Write-Host "WARNING: No mcpServers found in desktop config." -ForegroundColor Yellow
    }
} elseif (Test-Path $claudeConfig) {
    Write-Host "Found CLI settings: $claudeConfig" -ForegroundColor Green
} else {
    Write-Host "WARNING: No Claude config found. Run 'claude mcp add' to set up Robinhood MCP." -ForegroundColor Yellow
}

# ── Done ──────────────────────────────────────────────────
Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host "Task '$TASK_NAME' will run every 15 min on weekdays 8:15 AM–3:15 PM CST."
Write-Host "Logs saved to: $LOG_DIR"
Write-Host "`nTo test immediately: Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host "To view logs:        Get-Content `"$LOG_DIR\*.log`" | Select -Last 50"
Write-Host "To disable:          Disable-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host "To remove:           Unregister-ScheduledTask -TaskName '$TASK_NAME' -Confirm:`$false"
