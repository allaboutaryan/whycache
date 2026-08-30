"""How common is Docker build cache waste, really?

Reads each repo's Dockerfile and .dockerignore straight from the GitHub API —
no clones, no builds — and looks for one pattern: a whole-context COPY sitting
above expensive work, with .git not excluded.

That pattern means every commit invalidates the build. The interesting part is
how many of them cannot simply add .git to .dockerignore, because their build
reads git metadata to compute a version.

    python research/survey.py            # ~400 repos, resumable
    python research/survey.py 150        # fewer

Responses are cached in research/cache.json, so re-runs cost nothing and the
numbers stay reproducible.
"""

import base64
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whycache.blame import GIT_NEEDED

HERE = Path(__file__).resolve().parent
CACHE_PATH = HERE / "cache.json"
API = "https://api.github.com"

# Popular repos, spread across ecosystems so the result is not one language's
# habits. Anything below a few hundred stars is unlikely to have a real build.
QUERIES = [
    # Most-starred repos by language are dominated by awesome-lists, books and
    # tutorials, which ship no container at all. Target things people actually
    # deploy instead - the hit rate goes from ~17% to something useful, and
    # "popular deployable software" is the honest description of the sample.
    "stars:>1000 topic:docker",
    "stars:>1000 topic:kubernetes",
    "stars:>500 topic:self-hosted",
    "stars:>1000 topic:devops",
    "stars:>500 topic:microservices",
    "stars:>1000 topic:monitoring",
    "stars:>1000 topic:database",
    "stars:>1000 topic:api",
    "stars:>500 topic:web-server",
    "stars:>1000 topic:machine-learning topic:server",
]

# Steps that cost real time when a cache miss lands above them.
EXPENSIVE = re.compile(
    r"\b(apt-get|apt|apk|yum|dnf)\s+(install|add)|"
    r"\b(pip|pip3)\s+install|\bpoetry\s+install|\bpipenv\s+install|"
    r"\bnpm\s+(ci|install)|\byarn\s+(install)?|\bpnpm\s+(install|fetch)|"
    r"\bgo\s+(build|mod\s+download)|\bcargo\s+(build|fetch)|"
    r"\bmvn\b|\bgradle\b|\bmake\b|\bcmake\b|\bbundle\s+install",
    re.I,
)

# COPY . /dst, COPY --chown=x . /dst, ADD . /dst — the whole context in one go.
WIDE_COPY = re.compile(r"^(COPY|ADD)\s+((?:--\S+\s+)*)\.\s+\S+\s*$", re.I)

TOKEN = subprocess.run(["gh", "auth", "token"],
                       capture_output=True, text=True).stdout.strip()
_cache = json.loads(CACHE_PATH.read_text("utf-8")) if CACHE_PATH.exists() else {}


def api(path):
    """GET a JSON endpoint, waiting out secondary rate limits."""
    for attempt in range(5):
        req = urllib.request.Request(
            f"{API}{path}",
            headers={"Authorization": f"Bearer {TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "whycache-survey"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429):
                time.sleep(2 ** attempt * 5)
                continue
            return None
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** attempt)
    return None


def contents(repo, path):
    """A file's text, or None. Cached, including the misses."""
    key = f"{repo}:{path}"
    if key in _cache:
        return _cache[key]
    body = api(f"/repos/{repo}/contents/{path}")
    text = None
    if body and body.get("encoding") == "base64":
        try:
            text = base64.b64decode(body["content"]).decode("utf-8", "replace")
        except Exception:
            text = None
    _cache[key] = text
    return text


def search_repos(limit):
    """Repo full names, most-starred first, spread across the query set."""
    per_query = max(1, limit // len(QUERIES))
    names, seen = [], set()
    for q in QUERIES:
        for page in range(1, per_query // 100 + 2):
            body = api(f"/search/repositories?q={urllib.parse.quote(q)}"
                       f"&sort=stars&order=desc&per_page=100&page={page}")
            if not body or not body.get("items"):
                break
            for item in body["items"]:
                name = item["full_name"]
                if name not in seen:
                    seen.add(name)
                    names.append((name, item.get("language") or "?",
                                  item.get("stargazers_count", 0)))
            if len(seen) >= limit:
                return names[:limit]
            time.sleep(2)  # search allows 30/min
    return names[:limit]


def instructions(dockerfile):
    """Logical instructions, with line continuations joined."""
    text = re.sub(r"\\\s*\n", " ", dockerfile)
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def analyse(entry):
    repo, language, stars = entry
    df = contents(repo, "Dockerfile")
    if df is None:
        return None

    instrs = instructions(df)
    wide_at = next((i for i, ins in enumerate(instrs) if WIDE_COPY.match(ins)), None)
    below = 0
    if wide_at is not None:
        below = sum(1 for ins in instrs[wide_at + 1:]
                    if ins.upper().startswith("RUN") and EXPENSIVE.search(ins))

    di = contents(repo, ".dockerignore")
    ignores_git = bool(di and re.search(r"^\s*\.git\s*/?\s*$", di, re.M))

    needs_git = bool(GIT_NEEDED.search(df))
    if not needs_git and below:
        for f in ("pyproject.toml", "setup.py", "setup.cfg", "Makefile"):
            t = contents(repo, f)
            if t and GIT_NEEDED.search(t):
                needs_git = True
                break

    wasting = bool(below) and not ignores_git
    return {
        "repo": repo, "language": language, "stars": stars,
        "dockerignore": "none" if di is None else ("no .git" if not ignores_git else "ok"),
        "expensive_below": below,
        "wasting": wasting,
        "needs_git": needs_git,
        "pr_safe": wasting and not needs_git,
    }


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    print(f"searching for {limit} repos...", file=sys.stderr)
    entries = search_repos(limit)
    print(f"reading Dockerfiles from {len(entries)} repos...", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=12) as pool:
        rows = [r for r in pool.map(analyse, entries) if r]
    CACHE_PATH.write_text(json.dumps(_cache), encoding="utf-8")

    wasting = [r for r in rows if r["wasting"]]
    blocked = [r for r in wasting if r["needs_git"]]
    safe = sorted((r for r in wasting if r["pr_safe"]),
                  key=lambda r: (-r["expensive_below"], -r["stars"]))

    def pct(n, d):
        return f"{100 * n / d:.0f}%" if d else "-"

    print(f"\n{'':32}{'count':>7}{'share':>8}")
    print("-" * 47)
    print(f"{'repos searched':32}{len(entries):>7}")
    print(f"{'with a root Dockerfile':32}{len(rows):>7}{pct(len(rows), len(entries)):>8}")
    print(f"{'wasting cache on every commit':32}{len(wasting):>7}{pct(len(wasting), len(rows)):>8}")
    print(f"{'  ...and the simple fix breaks':32}{len(blocked):>7}{pct(len(blocked), len(wasting)):>8}")
    print(f"{'  ...safe to send a PR':32}{len(safe):>7}{pct(len(safe), len(wasting)):>8}")

    print("\nby language (repos with a Dockerfile / of those, wasting)")
    langs = {}
    for r in rows:
        a, b = langs.get(r["language"], (0, 0))
        langs[r["language"]] = (a + 1, b + int(r["wasting"]))
    for lang, (total, bad) in sorted(langs.items(), key=lambda kv: -kv[1][0])[:10]:
        print(f"  {lang:<14}{total:>5}{bad:>7}{pct(bad, total):>8}")

    print(f"\nPR queue — safe to fix, most expensive first ({len(safe)} repos)")
    print(f"{'repo':<44}{'stars':>7}{'costly steps below':>20}  .dockerignore")
    print("-" * 92)
    for r in safe[:25]:
        print(f"{r['repo']:<44}{r['stars']:>7}{r['expensive_below']:>20}  {r['dockerignore']}")

    print(f"\nblocked — .git is wrecking the cache but the build reads it ({len(blocked)})")
    for r in sorted(blocked, key=lambda r: -r["stars"])[:12]:
        print(f"  {r['repo']:<44}{r['stars']:>7}")

    (HERE / "survey.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\nwrote research/survey.json ({len(rows)} rows)")


if __name__ == "__main__":
    main()
