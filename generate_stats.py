#!/usr/bin/env python3
"""
Generates profile SVG cards (stats, languages, achievements) using the GitHub GraphQL API.
Standard library only. Runs inside GitHub Actions; no third-party hosting required.

Env:
  GH_USER   GitHub username (default: TanmayShil)
  GH_TOKEN  Token (GITHUB_TOKEN works for public data; a PAT adds private contributions)

Flags:
  --placeholder   write "generating..." placeholder SVGs (no network)
  --mock          render with sample data (for local preview, no network)
"""
import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from html import escape

USER = os.environ.get("GH_USER", "TanmayShil")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT = "assets"

BG, BORDER, ACCENT, TEXT, MUTED = "#1c1917", "#44403c", "#0891b2", "#ffffff", "#a8a29e"
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Arial, sans-serif"


# --------------------------------------------------------------------------- API
def gql(query, variables=None):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-generator",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GitHub API HTTP error {e.code}: {e.read().decode()[:300]}")
    if "errors" in data and not data.get("data"):
        raise SystemExit(f"GitHub API error: {data['errors']}")
    return data["data"]


PROFILE_Q = """
query($login:String!, $after:String){
  user(login:$login){
    name login createdAt
    followers{totalCount}
    repositories(ownerAffiliations:OWNER, isFork:false, first:100, after:$after,
                 orderBy:{field:STARGAZERS, direction:DESC}){
      totalCount
      pageInfo{hasNextPage endCursor}
      nodes{
        stargazerCount forkCount
        languages(first:10, orderBy:{field:SIZE, direction:DESC}){
          edges{size node{name color}}
        }
      }
    }
    contributionsCollection{
      contributionCalendar{
        totalContributions
        weeks{contributionDays{contributionCount date}}
      }
    }
  }
}
"""

YEAR_Q = """
query($login:String!, $from:DateTime!, $to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from, to:$to){
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
    }
  }
}
"""


def compute_streaks(weeks):
    days = sorted(
        (d["date"], d["contributionCount"]) for w in weeks for d in w["contributionDays"]
    )
    today = date.today().isoformat()
    days = [d for d in days if d[0] <= today]
    longest = run = 0
    for _, c in days:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)
    current = 0
    idx = len(days) - 1
    if idx >= 0 and days[idx][1] == 0:  # today may not have contributions yet
        idx -= 1
    while idx >= 0 and days[idx][1] > 0:
        current += 1
        idx -= 1
    return current, longest


def fetch_stats():
    if not TOKEN:
        raise SystemExit("GH_TOKEN is empty")
    stars = forks = repos = 0
    langs = {}
    after = None
    first = None
    while True:
        u = gql(PROFILE_Q, {"login": USER, "after": after})["user"]
        if u is None:
            raise SystemExit(f"User '{USER}' not found")
        first = first or u
        repos = u["repositories"]["totalCount"]
        for r in u["repositories"]["nodes"]:
            stars += r["stargazerCount"]
            forks += r["forkCount"]
            for e in r["languages"]["edges"]:
                n = e["node"]["name"]
                cur = langs.get(n, {"size": 0, "color": e["node"]["color"] or "#8b949e"})
                cur["size"] += e["size"]
                langs[n] = cur
        pi = u["repositories"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        after = pi["endCursor"]

    created = datetime.fromisoformat(first["createdAt"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    commits = prs = issues = reviews = 0
    for year in range(created.year, now.year + 1):
        c = gql(
            YEAR_Q,
            {"login": USER, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]
        prs += c["totalPullRequestContributions"]
        issues += c["totalIssueContributions"]
        reviews += c["totalPullRequestReviewContributions"]

    cal = first["contributionsCollection"]["contributionCalendar"]
    current, longest = compute_streaks(cal["weeks"])
    return {
        "name": first["name"] or first["login"],
        "stars": stars,
        "forks": forks,
        "repos": repos,
        "followers": first["followers"]["totalCount"],
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "reviews": reviews,
        "year_contribs": cal["totalContributions"],
        "current_streak": current,
        "longest_streak": longest,
        "years": max(0, (now - created).days // 365),
        "langs": langs,
    }


def mock_stats():
    return {
        "name": "Tanmay Shil", "stars": 12, "forks": 3, "repos": 24, "followers": 18,
        "commits": 1432, "prs": 87, "issues": 9, "reviews": 21,
        "year_contribs": 910, "current_streak": 6, "longest_streak": 41, "years": 4,
        "langs": {
            "TypeScript": {"size": 520000, "color": "#3178c6"},
            "JavaScript": {"size": 410000, "color": "#f1e05a"},
            "CSS": {"size": 120000, "color": "#563d7c"},
            "HTML": {"size": 80000, "color": "#e34c26"},
            "Python": {"size": 50000, "color": "#3572A5"},
            "C": {"size": 20000, "color": "#555555"},
        },
    }


# ------------------------------------------------------------------------ render
def fmt(n):
    if n >= 10000:
        return f"{n/1000:.0f}k"
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def svg_open(w, h, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>"
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="10" fill="{BG}" stroke="{BORDER}"/>'
    )


def heading(text, w):
    return (
        f'<text x="24" y="36" font-family="{FONT}" font-size="18" font-weight="700" fill="{ACCENT}">{escape(text)}</text>'
        f'<line x1="24" y1="48" x2="{w-24}" y2="48" stroke="{BORDER}"/>'
    )


def stats_svg(s):
    w, h = 700, 250
    rows_left = [
        ("Total Stars Earned", fmt(s["stars"])),
        ("Total Commits", fmt(s["commits"])),
        ("Total Pull Requests", fmt(s["prs"])),
        ("Total Issues", fmt(s["issues"])),
        ("Code Reviews", fmt(s["reviews"])),
    ]
    rows_right = [
        ("Public Repositories", fmt(s["repos"])),
        ("Followers", fmt(s["followers"])),
        ("Contributions (last year)", fmt(s["year_contribs"])),
        ("Current Streak", f'{s["current_streak"]} days'),
        ("Longest Streak (1 yr)", f'{s["longest_streak"]} days'),
    ]
    out = [svg_open(w, h, f'{s["name"]} GitHub stats'), heading(f'{s["name"]}\u2019s GitHub Stats', w)]
    for col, rows in enumerate((rows_left, rows_right)):
        x0 = 24 + col * 340
        for i, (label, val) in enumerate(rows):
            y = 84 + i * 30
            out.append(f'<circle cx="{x0+5}" cy="{y-5}" r="4" fill="{ACCENT}"/>')
            out.append(f'<text x="{x0+18}" y="{y}" font-family="{FONT}" font-size="14" fill="{MUTED}">{escape(label)}</text>')
            out.append(f'<text x="{x0+300}" y="{y}" text-anchor="end" font-family="{FONT}" font-size="15" font-weight="700" fill="{TEXT}">{escape(val)}</text>')
    out.append("</svg>")
    return "".join(out)


def langs_svg(s):
    langs = sorted(s["langs"].items(), key=lambda kv: kv[1]["size"], reverse=True)
    top = langs[:6]
    total = sum(v["size"] for _, v in top) or 1
    w, h = 700, 190
    out = [svg_open(w, h, "Top languages"), heading("Top Languages", w)]
    bar_x, bar_w, bar_y = 24, w - 48, 66
    out.append(
        f'<clipPath id="r"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="12" rx="6"/></clipPath>'
        f'<g clip-path="url(#r)">'
    )
    x = bar_x
    for _, v in top:
        seg = bar_w * v["size"] / total
        out.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{seg:.2f}" height="12" fill="{escape(v["color"])}"/>')
        x += seg
    out.append("</g>")
    for i, (name, v) in enumerate(top):
        col, row = i % 3, i // 3
        lx, ly = 24 + col * 225, 112 + row * 30
        pct = 100 * v["size"] / total
        out.append(f'<circle cx="{lx+6}" cy="{ly-5}" r="6" fill="{escape(v["color"])}"/>')
        out.append(
            f'<text x="{lx+20}" y="{ly}" font-family="{FONT}" font-size="14" fill="{TEXT}">'
            f'{escape(name)} <tspan fill="{MUTED}">{pct:.1f}%</tspan></text>'
        )
    out.append("</svg>")
    return "".join(out)


TIERS = [
    ("Starter", "#78716c"),
    ("Bronze", "#cd7f32"),
    ("Silver", "#cbd5e1"),
    ("Gold", "#fbbf24"),
    ("Platinum", "#22d3ee"),
]


def hexagon(cx, cy, r):
    pts = []
    for k in range(6):
        a = math.radians(60 * k - 30)
        pts.append(f"{cx + r*math.cos(a):.1f},{cy + r*math.sin(a):.1f}")
    return " ".join(pts)


def achievements_svg(s):
    items = [
        ("Stars", s["stars"], [1, 10, 50, 200]),
        ("Commits", s["commits"], [100, 500, 1500, 5000]),
        ("Pull Requests", s["prs"], [5, 25, 100, 300]),
        ("Repositories", s["repos"], [5, 15, 40, 100]),
        ("Followers", s["followers"], [5, 25, 100, 500]),
        ("Code Reviews", s["reviews"], [1, 10, 50, 200]),
        ("Longest Streak", s["longest_streak"], [3, 7, 30, 100]),
        ("Years on GitHub", s["years"], [1, 2, 4, 7]),
    ]
    w, cell_h = 700, 118
    h = 64 + 2 * cell_h
    out = [svg_open(w, h, "GitHub achievements"), heading("Achievements", w)]
    for i, (title, val, th) in enumerate(items):
        col, row = i % 4, i // 4
        cx = 24 + col * 163 + 80
        cy = 64 + row * cell_h + 38
        tier = sum(1 for t in th if val >= t)
        label, color = TIERS[tier]
        out.append(f'<polygon points="{hexagon(cx, cy, 30)}" fill="{color}" fill-opacity="0.15" stroke="{color}" stroke-width="2.5"/>')
        out.append(f'<text x="{cx}" y="{cy+6}" text-anchor="middle" font-family="{FONT}" font-size="16" font-weight="700" fill="{TEXT}">{escape(fmt(val))}</text>')
        out.append(f'<text x="{cx}" y="{cy+52}" text-anchor="middle" font-family="{FONT}" font-size="13" font-weight="600" fill="{TEXT}">{escape(title)}</text>')
        out.append(f'<text x="{cx}" y="{cy+68}" text-anchor="middle" font-family="{FONT}" font-size="11" fill="{color}">{label}</text>')
    out.append("</svg>")
    return "".join(out)


def placeholder_svg(title, w=700, h=120, msg="Generating\u2026 this card appears after the first workflow run"):
    return (
        svg_open(w, h, title)
        + heading(title, w)
        + f'<text x="{w/2}" y="{h-30}" text-anchor="middle" font-family="{FONT}" font-size="13" fill="{MUTED}">{escape(msg)}</text></svg>'
    )


# -------------------------------------------------------------------------- main
def write(name, content):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(content)
    print("wrote", os.path.join(OUT, name))


def main():
    if "--placeholder" in sys.argv:
        write("stats.svg", placeholder_svg("GitHub Stats"))
        write("languages.svg", placeholder_svg("Top Languages"))
        write("achievements.svg", placeholder_svg("Achievements"))
        write("snake.svg", placeholder_svg("Contribution Snake"))
        write("snake-dark.svg", placeholder_svg("Contribution Snake"))
        return
    s = mock_stats() if "--mock" in sys.argv else fetch_stats()
    write("stats.svg", stats_svg(s))
    write("languages.svg", langs_svg(s))
    write("achievements.svg", achievements_svg(s))


if __name__ == "__main__":
    main()
