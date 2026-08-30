"""Running the build and reading what Docker did.

Everything here is about turning BuildKit's progress stream into an ordered
list of steps and which of them missed cache. Nothing here decides *why* a
step missed - that is blame.py's job.
"""

import json
import re
import subprocess
from datetime import datetime

# Real build steps. Multi-stage builds prefix the stage name, so both of these
# must match or the tool silently sees zero steps and calls a five-minute build
# "fully cached":
#   [4/5] RUN pip install ...
#   [builder 3/7] RUN apt update ...
#   [stage-1 2/3] COPY --from=builder ...
RE_STEP = re.compile(r"^\[(?:([^\]\s]+)\s+)?(\d+)/(\d+)\]\s*(.*)$")


def _ts(s):
    """BuildKit mixes UTC 'Z' and local offsets, with nanosecond precision."""
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_build(context, extra=()):
    """Run the build, return (returncode, vertexes-by-digest, raw output)."""
    cmd = ["docker", "build", "--progress=rawjson", *extra, "."]
    p = subprocess.run(cmd, cwd=context, capture_output=True, text=True)
    out = p.stdout + p.stderr

    vertexes = {}
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        for v in obj.get("vertexes", []):
            # vertexes are re-emitted as they progress; last state wins
            vertexes.setdefault(v["digest"], {}).update(v)
    return p.returncode, vertexes, out


def steps_of(vertexes):
    """Real build steps, in execution order.

    BuildKit emits vertexes in *completion* order, and that order changes
    between runs, so output order is never trustworthy. The [i/n] index only
    orders steps *within* one stage, which is not enough for multi-stage
    builds - so order by the reported start time, which is the real thing.
    """
    steps = []
    for v in vertexes.values():
        m = RE_STEP.match(v.get("name", ""))
        if not m:
            continue
        started = v.get("started")
        secs = None
        if started and v.get("completed"):
            secs = (_ts(v["completed"]) - _ts(started)).total_seconds()
        steps.append({
            "stage": m.group(1),
            "idx": int(m.group(2)),
            "instr": m.group(4),
            "cached": bool(v.get("cached")),
            "secs": secs,
            "started": _ts(started) if started else None,
        })
    # steps with no start time sort last; they are the ones we know least about
    return sorted(steps, key=lambda s: (s["started"] is None, s["started"], s["idx"]))


def real_steps(steps):
    """Steps that can meaningfully miss.

    FROM is excluded: base-image resolution reports DONE and never CACHED, so
    it always looks like a miss.

    ponytail: this also hides a genuinely changed base image. Comparing the
    resolved base digest across runs would catch that separately.
    """
    return [s for s in steps if not s["instr"].upper().startswith("FROM ")]


def first_miss(steps):
    """Earliest non-cached step. None => fully cached."""
    for s in real_steps(steps):
        if not s["cached"]:
            return s
    return None


def cache_was_cold(steps):
    """True when nothing was cached at all.

    Only ever a hint. A miss at the very first step leaves nothing downstream
    that *could* be cached, so this is also what a perfectly ordinary early
    miss looks like - see the ordering note in report().
    """
    real = real_steps(steps)
    return bool(real) and not any(s["cached"] for s in real)
