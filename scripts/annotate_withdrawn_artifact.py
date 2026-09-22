#!/usr/bin/env python3
"""Prepend a withdrawal banner to an already-published artifact's saved HTML.

Detects WHICH withdrawn claims a given page actually makes and tailors the
banner to those, so a page is never labelled with a retraction it doesn't carry.
Skips (exit 2) when nothing withdrawn is found.

Usage: inject_banner.py <saved.html> <out.html>
"""
import re
import sys

# marker -> (bullet text). Ordered most-specific first.
CLAIMS = [
    # Bare decimals are guarded with (?<![\d.,]) so they cannot match inside a
    # larger number -- "60.1" was otherwise matching inside "$1260.15".
    (r'(?<![\d.,])236\.77', 'the <strong>+236.77%</strong> "with daily stop" return'),
    (r'(?<![\d.,])242\.07', 'the <strong>+242.07%</strong> "with daily stop" return'),
    (r'(?<![\d.,])248\.36', 'the <strong>+248.36%</strong> "with daily stop" return'),
    (r'(?<![\d.,])81\.67', 'the <strong>+81.67pp</strong> improvement'),
    (r'(?<![\d.,])83\.65', 'the <strong>+83.65pp</strong> improvement'),
    (r'(?<![\d.,])93\.26', 'the <strong>+93.26pp</strong> improvement'),
    (r'(?<![\d.,])513\.2', 'the <strong>+513.2%</strong> dev-window improvement'),
    (r'(?<![\d.,])60\.1\s*%', 'the <strong>"+60.1% validated out-of-sample"</strong> claim'),
    (r'(?<![\d.,])79\.2\s*%', 'the <strong>+79.2%</strong> holdout improvement'),
    (r'(?<![\d.,])75\.3\s*%', 'the <strong>+75.3%</strong> holdout-with-stop return'),
    (r'(?<![\d.,])45\.0\s*%|\$36,027', 'the <strong>+45.0% / $36,027 "holdout"</strong>'),
    (r'(?<![\d.,])187\.5|(?<![\d.,])206\s*%', 'the <strong>+187.5-206%</strong> projected range'),
    (r'(?<![\d.,])145\.80', 'the superseded <strong>+145.80%</strong> baseline'),
    # NOTE: +158.42% is NOT withdrawn -- it is the verified baseline (realized
    # + end-of-window mark-to-market on $80k) and reproduces to the cent. Do not
    # add a rule for it.
    (r'273,659|193,659|189,418', 'the inflated <strong>with-stop ending equity</strong>'),
    (r'39,964|28,801', 'the hypothetical <strong>with-stop period P&amp;L</strong>'),
    (r'26,748', 'the <strong>+$26,748.35</strong> "savings from stops"'),
    (r'\+\s*202\s*%', 'the <strong>+202% better</strong> claim'),
    (r'66,922|66,821|65,337|74,605', 'the claimed <strong>daily-stop savings</strong>'),
    (r'188,571|189,730|56,571|56,919', 'the claimed <strong>with-stop P&amp;L</strong>'),
    (r'(?<![\d.,])52\.0\s*%|(?<![\d.,])52\.9\s*%', 'the <strong>+52.0% / +52.9%</strong> stop improvements'),
    (r'(?<![\d.,])188\.6\s*%|(?<![\d.,])189\.7\s*%', 'the <strong>188.6% / 189.7%</strong> with-stop returns'),
    (r'[Hh]ourly [Ss]top', 'the <strong>hourly-stop variant</strong>, which was never replayed at all'),
    (r'198,687|64,573|32,958', 'the claimed <strong>with-stop window P&amp;L</strong>'),
    (r'(?<![\d.,])662\.3|(?<![\d.,])248\.7\s*pp', 'the <strong>662.3% / +248.7pp</strong> with-stop return'),
    (r'(?<![\d.,])215\.2\s*%|(?<![\d.,])109\.9\s*%', 'the <strong>109.9% / 215.2%</strong> with-stop window returns'),
    (r'1,597\.10', 'the <strong>$1,597.10 &ldquo;saved by the daily stop&rdquo;</strong> on Aug&nbsp;6'),
    (r'1,699\.40', 'the <strong>-$1,699.40</strong> &ldquo;worst-case day&rdquo; the stop is said to have prevented'),
    (r'1,555', 'the <strong>+$1,555 daily-stop swing</strong>'),
    (r'985\.88|(?<![\d.,])9\.86\s*%', 'the <strong>+$985.88 / +9.86%</strong> with-stop result'),
    (r'3,768\.33|(?<![\d.,])37\.68\s*%', 'the <strong>+$3,768.33 / +37.68%</strong> with-stop total'),
    (r'3,096\.52|(?<![\d.,])30\.96\s*pp', 'the <strong>+$3,096.52 / +30.96pp</strong> stop benefit'),
]

# A page must mention the stop or a withdrawn baseline to qualify at all.
QUALIFY = re.compile(r'daily stop|Daily Stop|DAILY_STOP|hourly stop|Hourly Stop|145\.80',
                     re.I)

BANNER = """
<div style="background:#2a1416;border:2px solid #a32c2c;border-left:8px solid #a32c2c;
            border-radius:6px;padding:18px 20px;margin:0 0 24px 0;color:#f4e6e6;
            font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            font-size:14px;line-height:1.6">
  <div style="font-size:16px;font-weight:700;color:#ff9d9d;margin-bottom:10px">
    &#9888;&#65039; WITHDRAWN &mdash; corrected 22 September 2026
  </div>
  <p style="margin:0 0 10px">
    The figures on this page are <strong>not valid</strong> and should not be used.
    Specifically withdrawn here: {claims}.
  </p>
  <p style="margin:0 0 10px">
    <strong>Why.</strong> The daily-stop variants were never produced by replaying the
    trading engine. They were simulated by capping a frozen <code>day_pnl</code> series
    (<code>stop_amount = 30000 * stop_level</code>; <code>cmd_plan</code> never called).
    Capping a fixed P&amp;L series cannot model a stop, because liquidating positions
    changes which positions exist tomorrow &mdash; and therefore the tranche index,
    sizing, hold timing, the peak-sell reference and settlement. The whole path
    diverges. Such a script returns whatever cap was typed into it. It also applied a
    $300 cap (1% of $30,000) to P&amp;L generated by an <strong>$80,000</strong> run.
  </p>
  <p style="margin:0 0 10px">
    <strong>The &ldquo;out-of-sample holdout&rdquo; was not one.</strong> Its $36,027 is
    exactly the Jul&nbsp;6&ndash;Aug&nbsp;3 slice of the <em>same</em> continuous run
    &mdash; nothing withheld, nothing re-fit &mdash; and its &ldquo;+45%&rdquo; divides
    that slice by the original $80,000 even though equity had already compounded to
    $162,679 by then. A genuine fresh holdout returns <strong>+11.73%</strong>.
  </p>
  <p style="margin:0 0 10px">
    <strong>What replay actually shows.</strong> Running the real engine with the
    daily-stop defect patched: <strong>+79.71% vs +155.10% baseline</strong> over six
    months, and <strong>+8.72% vs +11.73%</strong> on a genuine holdout. The stop
    roughly <strong>halves</strong> returns in both windows.
  </p>
  <p style="margin:0 0 10px">
    <strong>It was never live.</strong> The daily stop existed only on a development
    branch; the production branch the daily trigger checks out has never contained it.
    No real money was exposed to it.
  </p>
  <p style="margin:0">
    <strong>Verified baseline:</strong> +155.10% ($124,080.90 realized on $80,000,
    13&nbsp;Mar&nbsp;&ndash;&nbsp;4&nbsp;Sep&nbsp;2026), which reproduces to the cent via
    <code>scripts/margin_style_original_6month_backtest.py</code>. Corrected write-ups:
    <a href="https://claude.ai/artifact/Cj63BFGrfdT4iJmKZKwHzZ"
       style="color:#ffb3b3">Stop Variants, re-measured</a> &middot;
    <a href="https://claude.ai/artifact/JJ3ocArdStXwpUAfte94dB"
       style="color:#ffb3b3">P&amp;L Reconciliation</a>.
  </p>
</div>
"""


def main():
    src = open(sys.argv[1]).read()
    if 'WITHDRAWN &mdash; corrected 22 September 2026' in src:
        print('ALREADY BANNERED')
        return 3
    if not QUALIFY.search(src):
        print('NO WITHDRAWN CLAIM FOUND')
        return 2

    found = [text for pat, text in CLAIMS if re.search(pat, src)]
    if not found:
        print('NO WITHDRAWN CLAIM FOUND')
        return 2
    if len(found) == 1:
        claims = found[0]
    else:
        claims = ', '.join(found[:-1]) + ' and ' + found[-1]

    banner = BANNER.format(claims=claims)
    # Insert at the top of visible content: after the LAST <body ...> tag, which is
    # the inner document's own body on these double-wrapped published pages.
    matches = list(re.finditer(r'<body[^>]*>', src, re.I))
    if not matches:
        print('NO <body> TAG')
        return 4
    at = matches[-1].end()
    out = src[:at] + '\n' + banner + src[at:]
    open(sys.argv[2], 'w').write(out)
    print(f'BANNERED ({len(found)} claim(s)): ' + '; '.join(
        re.sub(r'<[^>]+>', '', f) for f in found))
    return 0


if __name__ == '__main__':
    sys.exit(main())
