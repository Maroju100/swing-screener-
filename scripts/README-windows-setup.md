# Headless Windows Setup — Confirmed Pullback Swing

Runs the agentic trading strategy every 15 min via Windows Task Scheduler,
even when no browser is open.

## Prerequisites

| Tool | Install |
|---|---|
| Node.js 18+ | https://nodejs.org |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Anthropic API key | https://console.anthropic.com |
| Robinhood MCP configured | See step 3 below |

---

## One-Time Setup (5 minutes)

### Step 1 — Download scripts
Copy `swing-screener.ps1` and `setup-task.ps1` to any folder on your PC.

### Step 2 — Run setup (as Administrator)
```powershell
# Right-click PowerShell → "Run as Administrator"
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser   # allow local scripts
cd C:\path\to\scripts
.\setup-task.ps1
```
This will:
- Prompt for your `ANTHROPIC_API_KEY`
- Install Claude CLI if missing
- Copy the runner script to `%USERPROFILE%\SwingScreener\`
- Register a Task Scheduler job (every 15 min, Mon–Fri, 9:15 AM–4:15 PM)

### Step 3 — Configure Robinhood MCP
If not already set up via the Claude desktop app:
```powershell
claude mcp add robinhood -- npx -y robinhood-claude-mcp
```
Or add to `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "RobinhoodClaude": {
      "command": "npx",
      "args": ["-y", "robinhood-claude-mcp"]
    }
  }
}
```

### Step 4 — Test it
```powershell
# Run one cycle immediately
Start-ScheduledTask -TaskName "SwingScreener-ConfirmedPullback"

# Watch the log
Get-Content "$env:USERPROFILE\SwingScreener\logs\*.log" | Select-Object -Last 50
```

---

## How it works

```
Every 15 min (Task Scheduler)
        │
        ▼
swing-screener.ps1
        │
        ├─ Check: weekday? market hours (9:30–4 PM CDT)?
        │         → skip if not
        │
        └─ claude --dangerously-skip-permissions -p "Start the 15-minute..."
                │
                ├─ Gets portfolio + quotes + positions (Robinhood MCP)
                ├─ Scores SNDK/WDC/MU/AMD/NVDA/TSM (0–10)
                ├─ Executes trades if score ≥ 6 (Agentic 2)
                ├─ Refreshes scan → data/live_scan.json
                ├─ Updates docs/index.html + Activity Log
                └─ Pushes commit to GitHub Pages
```

---

## Manage the task

```powershell
# View status
Get-ScheduledTask -TaskName "SwingScreener-ConfirmedPullback"

# Pause trading (e.g. before earnings)
Disable-ScheduledTask -TaskName "SwingScreener-ConfirmedPullback"

# Resume
Enable-ScheduledTask -TaskName "SwingScreener-ConfirmedPullback"

# Remove completely
Unregister-ScheduledTask -TaskName "SwingScreener-ConfirmedPullback" -Confirm:$false

# View last 7 days of logs
Get-ChildItem "$env:USERPROFILE\SwingScreener\logs" | Sort LastWriteTime -Desc
```

---

## Notes

- **Keep PC on** during market hours (9:30 AM–4 PM CDT, Mon–Fri). Sleep/hibernate stops the task.
- Timezone is set to **CST (UTC-6)**, market hours **8:30 AM–3:00 PM CST**. If you switch to CDT in summer, change offset to `-5` and times to `09:30`/`16:00` in `swing-screener.ps1`.
- Each cycle creates a timestamped log file. Logs older than 7 days are auto-deleted.
- The task runs under your user account so it has access to the same MCP credentials as the Claude desktop app.
