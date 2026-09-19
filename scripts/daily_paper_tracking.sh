#!/bin/bash
# Daily Entry Quality Filter Paper Tracking
# Run daily at 18:00 UTC (right after Margin-Style Live at 17:00 UTC)

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
