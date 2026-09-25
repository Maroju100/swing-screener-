#!/usr/bin/env python3
"""Refresh the paper-shadow table on margin_rule_research.html from the shadow log.

Rewrites only the text between /*SHADOW_START*/ and /*SHADOW_END*/. Figures are the
shadow log's own (paper, pre-run valuation) and the live broker total_value the
shadow step recorded; nothing is recomputed here.

    python3 scripts/build_shadow_dashboard_data.py
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'docs', 'margin_style_instant_shadow_log.json')
PAGE = os.path.join(ROOT, 'margin_rule_research.html')


def trades_text(r):
    parts = [f"sell {s['symbol']} ({s['reason']})" for s in r['sells']]
    parts += [f"buy {b['symbol']} ${b['notional']:,.0f}" for b in r['buys']]
    return ', '.join(parts)


rows = [{'date': r['date'], 'shadow': r['shadow_equity_pre_run'],
         'live': r.get('live_broker_total_value_pre_run'), 'trades': trades_text(r)}
        for r in json.load(open(LOG))['runs']]
page = open(PAGE).read()
new, n = re.subn(r'/\*SHADOW_START\*/.*?/\*SHADOW_END\*/',
                 '/*SHADOW_START*/' + json.dumps(rows, separators=(',', ':')) + '/*SHADOW_END*/',
                 page, flags=re.S)
assert n == 1, 'SHADOW markers not found exactly once'
open(PAGE, 'w').write(new)
print(f'{len(rows)} shadow row(s) written to {os.path.basename(PAGE)}')
