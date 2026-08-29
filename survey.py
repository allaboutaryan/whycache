"""Phase 4 survey: find repos whose Docker build cache is probably being wasted.

Static, no builds and no clones — just the Dockerfile and .dockerignore from
the GitHub API. The point is to shortlist candidates cheaply; the real numbers
still come from actually running whycache against the ones that look worst.

Usage: python survey.py
"""

import base64
import json
import re
import subprocess
import sys

from whycache.cli import GIT_NEEDED

REPOS = """
psf/black sqlfluff/sqlfluff traefik/whoami localstack/localstack
getredash/redash gohugoio/hugo goreleaser/goreleaser minio/minio
outline/outline directus/directus apache/airflow streamlit/streamlit
gradio-app/gradio ansible/ansible home-assistant/core netbox-community/netbox
grafana/grafana prometheus/prometheus influxdata/telegraf etcd-io/etcd
argoproj/argo-cd fluent/fluentd vitessio/vitess cockroachdb/cockroach
jaegertracing/jaeger open-telemetry/opentelemetry-collector caddyserver/caddy
hashicorp/vault hashicorp/consul kubernetes/dashboard nats-io/nats-server
redpanda-data/redpanda temporalio/temporal ClickHouse/ClickHouse
apache/superset mlflow/mlflow ray-project/ray dagster-io/dagster
prefecthq/prefect wandb/wandb
""".split()

# Steps that cost real time when a cache miss lands above them.
EXPENSIVE = re.compile(
    r"\b(apt-get|apt|apk|yum|dnf)\s+(install|add)|"
    r"\b(pip|pip3)\s+install|\bpoetry\s+install|\bpipenv\s+install|"
    r"\bnpm\s+(ci|install)|\byarn\s+(install)?|\bpnpm\s+(install|fetch)|"
    r"\bgo\s+(build|mod\s+download)|\bcargo\s+(build|fetch)|"
    r"\bmvn\b|\bgradle\b|\bmake\b|\bcmake\b|\bbundle\s+install",
    re.I,
)

def gh(repo, path):
    p = subprocess.run(
        ["gh", "api", f"repos/{repo}/contents/{path}", "--jq", ".content"],
        capture_output=True, text=True,
    )
    if p.returncode != 0 or not p.stdout.strip():
        return None
    try:
        return base64.b64decode(p.stdout).decode("utf-8", "replace")
    except Exception:
        return None


def instructions(dockerfile):
    """Logical instructions, with line continuations joined."""
    text = re.sub(r"\\\s*\n", " ", dockerfile)
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def analyse(repo):
    df = gh(repo, "Dockerfile")
    if df is None:
        return None

    di = gh(repo, ".dockerignore")
    instrs = instructions(df)

    # Where does a whole-context COPY happen, and what expensive work is below it?
    wide_copy_at = None
    for i, ins in enumerate(instrs):
        if re.match(r"^(COPY|ADD)\s+(?!--from)(\S+\s+)*?\.\s+\S+\s*$", ins, re.I) \
                or re.match(r"^(COPY|ADD)\s+\.\s+\S+$", ins, re.I):
            wide_copy_at = i
            break

    below = 0
    if wide_copy_at is not None:
        below = sum(1 for ins in instrs[wide_copy_at + 1:]
                    if ins.upper().startswith("RUN") and EXPENSIVE.search(ins))

    ignores_git = bool(di and re.search(r"^\s*\.git\s*/?\s*$", di, re.M))
    needs_git = bool(GIT_NEEDED.search(df))
    if not needs_git:
        for f in ("pyproject.toml", "setup.py", "setup.cfg"):
            t = gh(repo, f)
            if t and GIT_NEEDED.search(t):
                needs_git = True
                break

    # Risk: a whole-context COPY with expensive work under it, and .git not excluded.
    risk = 0
    if wide_copy_at is not None and below:
        risk = below * 2
        if di is None:
            risk += 3
        elif not ignores_git:
            risk += 2

    return {
        "repo": repo,
        "dockerignore": "none" if di is None else ("no .git" if not ignores_git else "ok"),
        "wide_copy": wide_copy_at is not None,
        "expensive_below": below,
        "needs_git": needs_git,
        "risk": risk,
    }


def main():
    rows = []
    for repo in REPOS:
        r = analyse(repo)
        print(("  ." if r else "  x") + f" {repo}", file=sys.stderr)
        if r:
            rows.append(r)

    rows.sort(key=lambda r: -r["risk"])
    print(f"\n{len(rows)} of {len(REPOS)} repos have a root Dockerfile\n")
    print(f"{'repo':<42}{'risk':>5}  {'.dockerignore':<14}"
          f"{'wide COPY':<11}{'costly steps below':<20}{'needs git'}")
    print("-" * 108)
    for r in rows:
        print(f"{r['repo']:<42}{r['risk']:>5}  {r['dockerignore']:<14}"
              f"{'yes' if r['wide_copy'] else 'no':<11}"
              f"{r['expensive_below']:<20}{'YES - do not ignore .git' if r['needs_git'] else ''}")

    with open("survey.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1)
    print(f"\nwrote survey.json ({len(rows)} rows)")


if __name__ == "__main__":
    main()
