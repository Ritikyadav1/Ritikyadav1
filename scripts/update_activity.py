"""Regenerate assets/activity-{dark,light}.svg from the public GitHub contribution calendar,
and sync the yearly total into the stats cards and README alt text.

Usage: python3 scripts/update_activity.py [user]
"""
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

USER = sys.argv[1] if len(sys.argv) > 1 else "Ritikyadav1"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
WEEKS = 52

PALETTES = {
    "dark": dict(bg="#161826", border="rgba(233,233,237,0.14)", accent="#b5abfc", bar="#9184d9",
                 ink="#e9e9ed", muted="#b2b6ca", faint="#9397ab"),
    "light": dict(bg="#f3f5fe", border="rgba(41,43,49,0.16)", accent="#5d5294", bar="#796cbf",
                  ink="#292b31", muted="#595d6c", faint="#656a7c"),
}


def parse(html):
    """Return ({cell_id: date}, {cell_id: count}) from the calendar HTML."""
    dates = {m[1]: date.fromisoformat(m[0]) for m in re.findall(
        r'<td[^>]*data-date="([\d-]+)"[^>]*id="(contribution-day-component-[\d-]+)"', html)}
    counts = {}
    for cell, text in re.findall(r'<tool-tip[^>]*for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)</tool-tip>', html):
        m = re.match(r"([\d,]+) contribution", text)
        counts[cell] = int(m[1].replace(",", "")) if m else 0
    return dates, counts


def weekly(dates, counts):
    """Sum days into Sunday-started weeks; return the last WEEKS as [(week_start, total)]."""
    weeks = defaultdict(int)
    for cell, d in dates.items():
        weeks[d.toordinal() - (d.isoweekday() % 7)] += counts.get(cell, 0)
    return [(date.fromordinal(k), weeks[k]) for k in sorted(weeks)][-WEEKS:]


def render(weeks, year_total, p):
    peak = max(c for _, c in weeks) or 1
    bars = []
    for i, (_, c) in enumerate(weeks):
        h = max(2.0, 88 * c / peak)  # 2px stub keeps empty weeks visible
        x = 32 + i * (816 - 31.4) / (WEEKS - 1)
        bars.append(f'<rect x="{x:.1f}" y="{160 - h:.1f}" width="10.4" height="{h:.1f}" rx="2.5" '
                    f'fill="{p["bar"]}" fill-opacity="{0.30 + 0.69 * i / (WEEKS - 1):.2f}"></rect>')
    first, last = weeks[0][0], weeks[-1][0]
    fmt = lambda d: d.strftime("%b ’%y")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="208" viewBox="0 0 880 208" font-family="Inter, -apple-system, &#34;Segoe UI&#34;, Helvetica, Arial, sans-serif">
<defs><linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="{p["ink"]}" stop-opacity="0"></stop><stop offset=".15" stop-color="{p["ink"]}" stop-opacity=".22"></stop><stop offset=".85" stop-color="{p["ink"]}" stop-opacity=".22"></stop><stop offset="1" stop-color="{p["ink"]}" stop-opacity="0"></stop></linearGradient></defs>
<rect x=".5" y=".5" width="879" height="207" rx="12" fill="{p["bg"]}" stroke="{p["border"]}"></rect>
<text x="32" y="34" font-size="12" fill="{p["accent"]}" font-weight="500" letter-spacing="1.4">COMMIT ACTIVITY</text><text x="32" y="58" font-size="13" fill="{p["muted"]}">Contributions per week, last {WEEKS} weeks · {year_total} in the last year · peak {peak}/week</text>{"".join(bars)}<rect x="32" y="172" width="816" height="1" fill="url(#fade)"></rect><text x="32" y="194" font-size="12" fill="{p["faint"]}">{fmt(first)}</text><text x="848" y="194" font-size="12" fill="{p["faint"]}" text-anchor="end">{fmt(last)}</text></svg>
'''


def main():
    req = urllib.request.Request(f"https://github.com/users/{USER}/contributions", headers={"User-Agent": "update-activity"})
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    dates, counts = parse(html)
    weeks = weekly(dates, counts)
    year_total = sum(counts.get(c, 0) for c in dates)
    assert len(weeks) == WEEKS, f"expected {WEEKS} weeks, got {len(weeks)}"
    assert sum(c for _, c in weeks) <= year_total
    for name, palette in PALETTES.items():
        (ASSETS / f"activity-{name}.svg").write_text(render(weeks, year_total, palette))
        # Keep the stats card's CONTRIBUTIONS figure in sync with the chart.
        stats = ASSETS / f"stats-{name}.svg"
        stats.write_text(re.sub(r"(CONTRIBUTIONS</text><text[^>]*>)\d+<", rf"\g<1>{year_total}<", stats.read_text()))
    readme = ASSETS.parent / "README.md"
    readme.write_text(re.sub(r"\d+ contributions,", f"{year_total} contributions,", readme.read_text()))
    print(f"{year_total} contributions in the last year; last {WEEKS} weeks: {[c for _, c in weeks]}")


if __name__ == "__main__":
    main()
