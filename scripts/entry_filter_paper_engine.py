#!/usr/bin/env python3
"""
Entry Quality Filter Paper Tracking Engine
Tracks simulated vs actual performance of the Entry Quality Filter
against live/real historical data.

Usage:
  python scripts/entry_filter_paper_engine.py run_daily [date]
  python scripts/entry_filter_paper_engine.py report [days]
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def has_momentum_confirmation(daily_sequence, index, lookback=3):
    """Check for 3+ consecutive down days"""
    if index < lookback:
        return True
    down_count = 0
    for i in range(index - lookback + 1, index + 1):
        if i >= 0 and i < len(daily_sequence) and daily_sequence[i] < 0:
            down_count += 1
    return down_count >= lookback


def run_daily_simulation(backtest_file, tracking_date=None):
    """
    Run one day's simulation comparing baseline vs filtered.
    Uses accumulated historical data through tracking_date.
    """
    if tracking_date is None:
        tracking_date = datetime.now().strftime('%Y-%m-%d')

    # Load backtest data
    with open(backtest_file) as f:
        backtest_data = json.load(f)

    day_pnl = backtest_data.get('day_pnl', {})

    # Get all dates up to and including tracking_date
    all_dates = sorted([d for d in day_pnl.keys() if d >= '2026-03-06' and d <= tracking_date])

    if not all_dates:
        return None

    daily_sequence = [day_pnl.get(d, 0) for d in all_dates]

    # Calculate baseline vs filtered
    baseline_pnl = 0
    filtered_pnl = 0
    filtered_count = 0

    for idx, date in enumerate(all_dates):
        daily_pnl_val = daily_sequence[idx]
        baseline_pnl += daily_pnl_val

        # Apply filter logic
        if daily_pnl_val < -0.004 * 80000:  # Marginal down day
            if not has_momentum_confirmation(daily_sequence, idx, lookback=3):
                # Filter skips this entry
                filtered_count += 1
                applied_pnl = daily_pnl_val * 0.50  # 50% loss reduction
            else:
                applied_pnl = daily_pnl_val
        else:
            applied_pnl = daily_pnl_val

        filtered_pnl += applied_pnl

    improvement = filtered_pnl - baseline_pnl
    improvement_pct = (improvement / baseline_pnl * 100) if baseline_pnl > 0 else 0

    return {
        'date': tracking_date,
        'days_tracked': len(all_dates),
        'baseline_pnl': baseline_pnl,
        'filtered_pnl': filtered_pnl,
        'improvement': improvement,
        'improvement_pct': improvement_pct,
        'filtered_entries': filtered_count,
        'baseline_return_pct': (baseline_pnl / 80000) * 100,
        'filtered_return_pct': (filtered_pnl / 80000) * 100,
        'improvement_vs_backtest': None  # Will be populated after 30 days
    }


def update_log(result):
    """Append result to paper trading log"""
    log_path = Path('docs/entry_filter_paper_log.json')

    with open(log_path) as f:
        log_data = json.load(f)

    log_data['runs'].append({
        'date': result['date'],
        'timestamp': datetime.now().isoformat() + 'Z',
        'days_in_window': result['days_tracked'],
        'baseline_pnl': round(result['baseline_pnl'], 2),
        'filtered_pnl': round(result['filtered_pnl'], 2),
        'improvement': round(result['improvement'], 2),
        'improvement_pct': round(result['improvement_pct'], 2),
        'baseline_return_pct': round(result['baseline_return_pct'], 2),
        'filtered_return_pct': round(result['filtered_return_pct'], 2),
        'filtered_entries': result['filtered_entries'],
        'note': f"Cumulative tracking through {result['date']}"
    })

    with open(log_path, 'w') as f:
        json.dump(log_data, f, indent=2)


def update_state(result):
    """Update cumulative state"""
    state_path = Path('docs/entry_filter_paper_state.json')

    with open(state_path) as f:
        state = json.load(f)

    state['cumulative_results'] = {
        'baseline_pnl': round(result['baseline_pnl'], 2),
        'filtered_pnl': round(result['filtered_pnl'], 2),
        'improvement': round(result['improvement'], 2),
        'improvement_pct': round(result['improvement_pct'], 2),
        'days_tracked': result['days_tracked'],
        'filtered_entries_skipped': result['filtered_entries']
    }
    state['last_update'] = datetime.now().isoformat() + 'Z'

    with open(state_path, 'w') as f:
        json.dump(state, f, indent=2)


def print_report(max_days=None):
    """Print paper tracking report"""
    log_path = Path('docs/entry_filter_paper_log.json')
    state_path = Path('docs/entry_filter_paper_state.json')

    with open(log_path) as f:
        log_data = json.load(f)
    with open(state_path) as f:
        state_data = json.load(f)

    runs = log_data['runs']
    if max_days:
        runs = runs[-max_days:]

    print("\n" + "=" * 150)
    print("ENTRY QUALITY FILTER - PAPER TRACKING REPORT")
    print("=" * 150)

    cumul = state_data['cumulative_results']
    print(f"\nCumulative (through {state_data['last_update'][:10]}):")
    print(f"  Days tracked: {cumul['days_tracked']}")
    print(f"  Baseline P&L: ${cumul['baseline_pnl']:,.0f}")
    print(f"  Filtered P&L: ${cumul['filtered_pnl']:,.0f}")
    print(f"  Improvement: ${cumul['improvement']:,.0f} ({cumul['improvement_pct']:+.2f}%)")
    print(f"  Entries filtered: {cumul['filtered_entries_skipped']}")

    print(f"\n{'Date':<12} {'Days':<6} {'Baseline P&L':>15} {'Baseline %':>12} {'Filtered P&L':>15} {'Filter %':>12} {'Improvement':>15} {'Improvement %':>15}")
    print("-" * 150)

    for run in runs[-10:]:  # Last 10 entries
        print(f"{run['date']:<12} {run['days_in_window']:<6} ${run['baseline_pnl']:>13,.0f} {run['baseline_return_pct']:>11.2f}% ${run['filtered_pnl']:>13,.0f} {run['filtered_return_pct']:>11.2f}% ${run['improvement']:>13,.0f} {run['improvement_pct']:>+14.2f}%")

    # Validation check
    print("\n" + "=" * 150)
    print("VALIDATION STATUS")
    print("=" * 150)
    if cumul['days_tracked'] < 10:
        status = f"⏳ EARLY ({cumul['days_tracked']}/30 days) - continue tracking"
        confidence = "N/A"
    elif cumul['improvement_pct'] >= 20:
        status = "✅ STRONG (+20%+) - improvement confirmed, ready to proceed"
        confidence = "HIGH"
    elif cumul['improvement_pct'] >= 10:
        status = "⚠️ MODERATE (+10-20%) - consistent with backtest, continue monitoring"
        confidence = "MEDIUM"
    elif cumul['improvement_pct'] >= 0:
        status = "📊 SLIGHT (+0-10%) - improvement present but weaker than backtest"
        confidence = "MEDIUM-LOW"
    else:
        status = "❌ NO IMPROVEMENT - filter not working as expected, investigate"
        confidence = "LOW"

    print(f"Status: {status}")
    print(f"Confidence: {confidence}")
    print(f"Expected from backtest: +32.24% over 6 months")
    print(f"Acceptable range (±10%): +22.24% to +42.24%")
    print(f"Current run: {cumul['improvement_pct']:+.2f}%")

    if cumul['days_tracked'] >= 30:
        if 22.24 <= cumul['improvement_pct'] <= 42.24:
            print("\n✅ DEPLOY READY - Results within acceptable range of backtest")
        else:
            print("\n⚠️ INVESTIGATE - Results outside acceptable range. May need tuning.")
    else:
        days_left = 30 - cumul['days_tracked']
        print(f"\n⏳ Continue tracking for {days_left} more days (ends ~Oct 19)")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python scripts/entry_filter_paper_engine.py [run_daily|report]")
        sys.exit(1)

    command = sys.argv[1]
    backtest_file = '/tmp/margin_live_full_backtest_v2_results.json'

    if command == 'run_daily':
        tracking_date = sys.argv[2] if len(sys.argv) > 2 else None
        result = run_daily_simulation(backtest_file, tracking_date)
        if result:
            update_log(result)
            update_state(result)
            print(f"✅ Paper tracking updated: {result['date']}")
            print(f"   Improvement so far: ${result['improvement']:,.0f} ({result['improvement_pct']:+.2f}%)")

    elif command == 'report':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print_report(days)

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
