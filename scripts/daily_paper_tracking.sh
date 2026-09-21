#!/bin/bash
# DISABLED 2026-09-21 — the engine this wraps produces invalid numbers.
# See scripts/entry_filter_paper_engine.py's docstring and Evidence Rule 1
# in CLAUDE.md. No trigger schedules this; it is kept only for history.
# (Without this guard the script would print "Paper tracking updated"
# even though both python calls now fail.)
echo "DISABLED 2026-09-21: entry-filter paper tracking produced invalid numbers." >&2
echo "See scripts/entry_filter_paper_engine.py docstring / CLAUDE.md Evidence Rule 1." >&2
exit 1

cd /home/user/swing-screener-

echo "================================"
echo "Entry Quality Filter Paper Tracking"
echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "================================"
echo ""

# Run the daily paper tracking
python scripts/entry_filter_paper_engine.py run_daily

# Print the report
python scripts/entry_filter_paper_engine.py report

echo ""
echo "Paper tracking updated. Results logged to docs/entry_filter_paper_log.json"
