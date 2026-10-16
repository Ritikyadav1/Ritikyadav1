"""Refresh the profile README's data-driven parts from GitHub:
activity chart (contribution calendar), stats cards, languages chart, top repos table and
stack badges (REST API plus each repo's manifests and imports).

Usage: GITHUB_TOKEN=... python3 scripts/update_stats.py [user]
The token is needed in practice: the stack scan makes ~2 API calls per repo, over the
unauthenticated limit of 60/hour.
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

USER = sys.argv[1] if len(sys.argv) > 1 else "Ritikyadav1"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
WEEKS = 52
TOP_LANGS = 4  # plus "Other"; the chart has 5 colors
TOP_REPOS = 5
SHORT_NAMES = {"Jupyter Notebook": "Jupyter"}  # keep legend entries within their 163px slot

# Stack badges: (category, badge, simple-icons logo, evidence keys). A badge shows when at least one
# repo has any of its keys; None means every repo. Keys: lang:<GitHub language>, npm:<package>,
# py:<import or pip name>, file:<marker found in the repo tree or homepage>.
STACK = [
    ("Languages", "TypeScript", "typescript", {"lang:TypeScript"}),
    ("Languages", "JavaScript", "javascript", {"lang:JavaScript"}),
    ("Languages", "Python", "python", {"lang:Python", "lang:Jupyter Notebook"}),
    ("Languages", "Java", "openjdk", {"lang:Java"}),
    ("Languages", "C++", "cplusplus", {"lang:C++"}),
    ("Languages", "C", "c", {"lang:C"}),
    ("Languages", "R", "r", {"lang:R"}),
    ("Frontend", "React", "react", {"npm:react"}),
    ("Frontend", "Next.js", "nextdotjs", {"npm:next"}),
    ("Frontend", "Redux", "redux", {"npm:redux", "npm:@reduxjs/toolkit", "npm:react-redux"}),
    ("Frontend", "Tailwind", "tailwindcss", {"npm:tailwindcss"}),
    ("Frontend", "Bootstrap", "bootstrap", {"npm:bootstrap", "npm:react-bootstrap"}),
    ("Frontend", "MUI", "mui", {"npm:@mui/material"}),
    ("Frontend", "Framer Motion", "framer", {"npm:framer-motion"}),
    ("Frontend", "Vite", "vite", {"npm:vite"}),
    ("Frontend", "Angular", "angular", {"npm:@angular/core"}),
    ("Frontend", "Electron", "electron", {"npm:electron"}),
    ("Frontend", "HTML5", "html5", {"lang:HTML"}),
    ("Frontend", "CSS3", "css3", {"lang:CSS"}),
    ("Backend", "Node.js", "nodedotjs", {"file:package.json"}),
    ("Backend", "Express", "express", {"npm:express"}),
    ("Backend", "NestJS", "nestjs", {"npm:@nestjs/core"}),
    ("Backend", "Django", "django", {"py:django"}),
    ("Backend", "Flask", "flask", {"py:flask"}),
    ("Backend", "JWT", "jsonwebtokens", {"npm:jsonwebtoken", "npm:@nestjs/jwt", "npm:passport-jwt"}),
    ("Backend", "Swagger", "swagger", {"npm:@nestjs/swagger", "npm:swagger-ui-express"}),
    ("Backend", "EJS", "ejs", {"npm:ejs", "lang:EJS"}),
    ("Data", "MongoDB", "mongodb", {"npm:mongoose", "npm:mongodb"}),
    ("Data", "MySQL", "mysql", {"npm:mysql", "npm:mysql2"}),
    ("Data", "PostgreSQL", "postgresql", {"npm:pg"}),
    ("Data", "SQLite", "sqlite", {"npm:sqlite3", "npm:better-sqlite3", "py:sqlite3"}),
    ("Data", "Redis", "redis", {"npm:redis", "npm:ioredis", "py:redis"}),
    ("Data", "Elasticsearch", "elasticsearch", {"npm:@elastic/elasticsearch", "py:elasticsearch"}),
    ("Data", "TypeORM", "typeorm", {"npm:typeorm"}),
    ("AI / ML", "TensorFlow", "tensorflow", {"py:tensorflow"}),
    ("AI / ML", "PyTorch", "pytorch", {"py:torch"}),
    ("AI / ML", "scikit-learn", "scikitlearn", {"py:sklearn", "py:scikit-learn"}),
    ("AI / ML", "OpenCV", "opencv", {"py:cv2", "py:opencv-python"}),
    ("AI / ML", "DeepFace", None, {"py:deepface"}),
    ("AI / ML", "NumPy", "numpy", {"py:numpy"}),
    ("AI / ML", "Pandas", "pandas", {"py:pandas"}),
    ("AI / ML", "Matplotlib", None, {"py:matplotlib"}),
    ("AI / ML", "Plotly", "plotly", {"py:plotly"}),
    ("Tooling", "Git", "git", None),
    ("Tooling", "Docker", "docker", {"file:docker"}),
    ("Tooling", "GitHub Actions", "githubactions", {"file:workflows"}),
    ("Tooling", "Jest", "jest", {"npm:jest"}),
    ("Tooling", "Vitest", "vitest", {"npm:vitest"}),
    ("Tooling", "Selenium", "selenium", {"npm:selenium-webdriver", "py:selenium"}),
    ("Tooling", "Vercel", "vercel", {"file:vercel"}),
    ("Tooling", "Netlify", "netlify", {"file:netlify"}),
]
DOCKER_FILES = {"Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}

PALETTES = {
    "dark": dict(bg="#161826", border="rgba(233,233,237,0.14)", accent="#b5abfc", bar="#9184d9",
                 ink="#e9e9ed", muted="#b2b6ca", faint="#9397ab",
                 langs=["#b5abfc", "#796cbf", "#5d5294", "#75798c", "#3f424d"]),
    "light": dict(bg="#f3f5fe", border="rgba(41,43,49,0.16)", accent="#5d5294", bar="#796cbf",
                  ink="#292b31", muted="#595d6c", faint="#656a7c",
                  langs=["#5d5294", "#796cbf", "#968ae0", "#9397ab", "#cfd3e5"]),
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


def fetch(url, api=False):
    headers = {"User-Agent": "update-activity"}
    if api and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30).read().decode()


def fetch_repos():
    repos, page = [], 1
    while batch := json.loads(fetch(f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100&page={page}", api=True)):
        repos += batch
        page += 1
    return repos


def language_shares(own):
    """Top languages by number of repos using them as primary language, rest folded into Other."""
    counts = Counter(r["language"] for r in own if r["language"])
    top = counts.most_common(TOP_LANGS)
    other = sum(counts.values()) - sum(c for _, c in top)
    if other:
        top.append(("Other", other))
    total = sum(counts.values())
    return [(SHORT_NAMES.get(n, n), c / total) for n, c in top], total


def render_languages(shares, n_repos, p):
    avail = 813 - 3 * (len(shares) - 1)  # 3px gaps between segments
    x, bar, legend = 32.0, [], []
    for i, ((name, share), color) in enumerate(zip(shares, p["langs"])):
        w = avail * share
        bar.append(f'<rect x="{x:.1f}" y="58" width="{w:.1f}" height="14" rx="4" fill="{color}"></rect>')
        x += w + 3
        cx = 37 + 163 * i
        legend.append(f'<circle cx="{cx}" cy="108" r="5" fill="{color}"></circle><text x="{cx + 12}" y="113" font-size="13" '
                      f'fill="{p["ink"]}">{html.escape(name)}<tspan dx="8" fill="{p["muted"]}">{round(share * 100)}%</tspan></text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="880" height="136" viewBox="0 0 880 136" font-family="Inter, -apple-system, &#34;Segoe UI&#34;, Helvetica, Arial, sans-serif">
<rect x=".5" y=".5" width="879" height="135" rx="12" fill="{p["bg"]}" stroke="{p["border"]}"></rect>
<text x="32" y="34" font-size="12" fill="{p["accent"]}" font-weight="500" letter-spacing="1.4">LANGUAGES</text><text x="848" y="34" font-size="12" fill="{p["faint"]}" text-anchor="end">by primary language · {n_repos} repos</text>{"".join(bar)}{"".join(legend)}</svg>
'''


def repos_table(own):
    """Markdown table of the most-starred repos, most recently pushed first among ties."""
    top = sorted(own, key=lambda r: (r["stargazers_count"], r["pushed_at"]), reverse=True)[:TOP_REPOS]
    rows = ["| Repository | Description | Language | Stars |", "| --- | --- | --- | ---: |"]
    for r in top:
        desc = (r["description"] or "—").strip().replace("|", "\\|")
        rows.append(f"| [{r['name']}]({r['html_url']}) | {desc} | {r['language'] or '—'} | {r['stargazers_count'] or '—'} |")
    return "\n".join(rows)


def raw_file(repo, path):
    """Contents of a file in a repo's default branch, or "" if it can't be fetched."""
    url = f"https://raw.githubusercontent.com/{USER}/{repo['name']}/{repo['default_branch']}/{urllib.parse.quote(path)}"
    try:
        return fetch(url)
    except (urllib.error.URLError, UnicodeDecodeError):
        return ""


def repo_evidence(repo):
    """Evidence keys (see STACK) for one repo, from its languages, file tree, manifests and imports."""
    api = f"https://api.github.com/repos/{USER}/{repo['name']}"
    ev = {f"lang:{lang}" for lang in json.loads(fetch(f"{api}/languages", api=True))}
    try:
        tree = json.loads(fetch(f"{api}/git/trees/{repo['default_branch']}?recursive=1", api=True))["tree"]
    except urllib.error.HTTPError:  # empty repo
        tree = []
    paths = [t["path"] for t in tree if t["type"] == "blob" and "node_modules/" not in t["path"]]
    for p in paths:
        base = p.rsplit("/", 1)[-1]
        ev |= {"file:docker"} if base in DOCKER_FILES else set()
        ev |= {"file:workflows"} if p.startswith(".github/workflows/") else set()
        ev |= {"file:vercel"} if base == "vercel.json" else set()
        ev |= {"file:netlify"} if base == "netlify.toml" else set()
        ev |= {"file:package.json"} if base == "package.json" else set()
    homepage = repo.get("homepage") or ""
    ev |= {"file:vercel"} if "vercel.app" in homepage else set()
    ev |= {"file:netlify"} if "netlify.app" in homepage else set()
    # ponytail: caps files scanned per repo to bound runtime; raise if a big monorepo hides deps.
    for p in [p for p in paths if p.endswith("package.json")][:10]:
        try:
            pkg = json.loads(raw_file(repo, p))
        except ValueError:
            continue
        ev |= {f"npm:{d}" for d in {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}}
    for p in [p for p in paths if p.endswith("requirements.txt")][:5]:
        ev |= {"py:" + re.split(r"[<>=!~\[ ;]", line.strip())[0].lower()
               for line in raw_file(repo, p).splitlines() if line.strip() and not line.lstrip().startswith(("#", "-"))}
    for p in [p for p in paths if p.endswith((".py", ".ipynb"))][:15]:
        # `(?:^|"|\\n)` also catches imports inside notebook JSON strings.
        ev |= {"py:" + m.split(".")[0].lower()
               for m in re.findall(r'(?:^|"|\\n)\s*(?:from|import)\s+([A-Za-z_][\w.]*)', raw_file(repo, p), re.M)}
    return ev


def badge(name, logo, n):
    label = urllib.parse.quote(name.replace("-", "--").replace("_", "__"), safe="")
    logo_q = f"&logo={logo}&logoColor=b5abfc" if logo else ""
    return (f'![{name}](https://img.shields.io/badge/{label}-423a6a?style=flat-square{logo_q}'
            f'&labelColor=232532 "Used in {n} repo{"s" * (n != 1)}")')


def stack_section(evidence):
    """Markdown badge groups for every STACK entry backed by at least one repo, most-used first."""
    groups = {}
    for cat, name, logo, keys in STACK:
        n = len(evidence) if keys is None else sum(1 for ev in evidence if ev & keys)
        if n:
            groups.setdefault(cat, []).append((n, name, logo))
    return "\n\n".join(f"**{cat}**\n\n" + "\n".join(badge(name, logo, n) for n, name, logo in sorted(items, key=lambda i: -i[0]))
                       for cat, items in groups.items())


def set_card(svg, label, value, sub):
    """Replace the big number and subtitle of the stats card titled `label`."""
    return re.sub(rf"({label}</text><text[^>]*>)[^<]*(</text><text[^>]*>)[^<]*<",
                  rf"\g<1>{value}\g<2>{sub}<", svg)


def main():
    html = fetch(f"https://github.com/users/{USER}/contributions")
    dates, counts = parse(html)
    weeks = weekly(dates, counts)
    year_total = sum(counts.get(c, 0) for c in dates)
    assert len(weeks) == WEEKS, f"expected {WEEKS} weeks, got {len(weeks)}"
    assert sum(c for _, c in weeks) <= year_total
    repos = fetch_repos()
    own = [r for r in repos if not r["fork"] and r["name"] != USER]  # skip forks and this profile repo
    n_repos, stars = len(repos), sum(r["stargazers_count"] for r in repos)
    starred = sum(1 for r in repos if r["stargazers_count"])
    langs = len({r["language"] for r in own} - {None})
    shares, n_lang_repos = language_shares(own)
    assert abs(sum(s for _, s in shares) - 1) < 1e-9
    for name, palette in PALETTES.items():
        (ASSETS / f"activity-{name}.svg").write_text(render(weeks, year_total, palette))
        (ASSETS / f"languages-{name}.svg").write_text(render_languages(shares, n_lang_repos, palette))
        stats = ASSETS / f"stats-{name}.svg"
        svg = stats.read_text()
        svg = set_card(svg, "REPOSITORIES", n_repos, "public")
        svg = set_card(svg, "STARS EARNED", stars, f"across {starred} repo{'s' * (starred != 1)}")
        svg = set_card(svg, "CONTRIBUTIONS", year_total, "last 12 months")
        svg = set_card(svg, "LANGUAGES", langs, "primary, across own repos")
        stats.write_text(svg)
    readme = ASSETS.parent / "README.md"
    text = re.sub(r"\d+ repositories, \d+ stars, \d+ contributions, \d+\+? languages",
                  f"{n_repos} repositories, {stars} stars, {year_total} contributions, {langs} languages", readme.read_text())
    lang_alt = "Primary languages: " + ", ".join(f"{n} {round(s * 100)}%" for n, s in shares)
    text = re.sub(r'alt="(Language breakdown|Primary languages:[^"]*)"', lambda _: f'alt="{lang_alt}"', text)
    text, n = re.subn(r"(## Top repos\n\n)\| Repository.*?(?=\n\n## )", lambda m: m[1] + repos_table(own), text, flags=re.S)
    assert n == 1, "Top repos table not found in README"
    stack = stack_section([repo_evidence(r) for r in own])
    text, n = re.subn(r"(## Stack\n\n).*?(?=\n\n## )", lambda m: m[1] + stack, text, flags=re.S)
    assert n == 1, "Stack section not found in README"
    readme.write_text(text)
    print(f"{n_repos} repos, {stars} stars ({starred} repos), {langs} languages, {year_total} contributions")
    print(lang_alt)
    print(f"last {WEEKS} weeks: {[c for _, c in weeks]}")


if __name__ == "__main__":
    main()
