#!/usr/bin/env python3
"""Every explored setup over an arbitrary window, at $15,000: how the account would stand at the end, day by day.
Same setups, engines, patches and gates as margin_style_6mo_all_setups.py (which this drives); only the window and
the data files differ. Data: data/margin_live_{daily,hourly}_to_2026-11-16.json = the to_2026-11-11 files plus the
official daily closes and 17:00 UTC hourly bars for Nov 12, 13 and 16 from the broker (fetched 2026-11-17).
HINDSIGHT TABLE on a short window: the top rows are not validated improvements.
MEASURED. Reproduce: python3 scripts/margin_style_all_setups_window.py 2026-11-04 2026-11-16
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
START, END = sys.argv[1], sys.argv[2]
import margin_style_all_setups_since_sep1 as A
ROOT = A.ROOT
A.D = os.path.join(ROOT, 'data', 'margin_live_daily_to_2026-11-16.json')
A.HR = os.path.join(ROOT, 'data', 'margin_live_hourly_to_2026-11-16.json')
import margin_style_6mo_all_setups as M
M.START, M.END = START, END
M.MONTHS = sorted({f'2026-{m:02d}' for m in range(int(START[5:7]), int(END[5:7]) + 1)})
M.OUTNAME = f'all_setups_{START}_{END}'
sys.argv = [sys.argv[0], START]
exec(compile(open(M.__file__).read().split("if __name__ == '__main__':", 1)[1].replace('\n    ', '\n'), M.__file__, 'exec'), vars(M))
import json
days = sorted(M.rows[0]['eq'])
json.dump({'start': START, 'end': END, 'capital': M.CAP, 'days': days,
           'rows': [{'label': x['label'], 'base': x['base'], 'study': x['study'], 'end': x['end'], 'max_dd': x['max_dd'], 'trades': x['trades'],
                     'daily_equity': [round(x['eq'][d], 2) for d in days if d in x['eq']]} for x in M.rows]},
          open(os.path.join(ROOT, 'data', 'research', f'all_setups_{START}_{END}_daily.json'), 'w'), indent=1)
print('days', days)
