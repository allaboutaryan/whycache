"""The step-name regex, pinned.

This is the piece that once made a five-minute multi-stage build report as
"fully cached": multi-stage vertexes are named `[builder 3/7]`, not `[3/7]`,
so a regex that only handles the second form matches nothing at all.

Run: python tests/test_build.py   (or: pytest tests/test_build.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whycache.build import RE_STEP, cache_was_cold, first_miss, real_steps

STEP_NAMES = [
    # (vertex name, expected stage, expected idx, expected instruction)
    ("[2/5] WORKDIR /app", None, 2, "WORKDIR /app"),
    ("[5/5] COPY . .", None, 5, "COPY . ."),
    ("[builder 3/7] RUN apt update", "builder", 3, "RUN apt update"),
    ("[stage-1 2/3] COPY --from=builder /opt/venv /opt/venv",
     "stage-1", 2, "COPY --from=builder /opt/venv /opt/venv"),
    ("[builder 1/7] FROM docker.io/library/python:3.14-slim", "builder", 1,
     "FROM docker.io/library/python:3.14-slim"),
]

NOT_STEPS = [
    "[internal] load build definition from Dockerfile",
    "[internal] load .dockerignore",
    "[auth] library/python:pull token for registry-1.docker.io",
    "resolve image config for docker.io/library/python:3.12-slim",
]


def step(idx, instr, cached, stage=None):
    return {"stage": stage, "idx": idx, "instr": instr, "cached": cached,
            "secs": 1.0, "started": None}


def run():
    failed = []

    for name, stage, idx, instr in STEP_NAMES:
        m = RE_STEP.match(name)
        if not m:
            failed.append(f"  step regex did not match: {name!r}")
        elif (m.group(1), int(m.group(2)), m.group(4)) != (stage, idx, instr):
            failed.append(f"  step regex wrong for {name!r}: "
                          f"got {(m.group(1), m.group(2), m.group(4))}")

    for name in NOT_STEPS:
        if RE_STEP.match(name):
            failed.append(f"  non-step matched as a step: {name!r}")

    # FROM always reports DONE rather than CACHED, so it must never be the miss
    from_only = [step(1, "FROM python:3.12", False), step(2, "WORKDIR /app", True)]
    if real_steps(from_only) != from_only[1:]:
        failed.append("  real_steps did not drop FROM")
    if first_miss(from_only) is not None:
        failed.append("  FROM was reported as the cache miss")

    mixed = [step(1, "FROM x", False), step(2, "WORKDIR /a", True),
             step(3, "COPY . .", False), step(4, "RUN make", False)]
    if (first_miss(mixed) or {}).get("idx") != 3:
        failed.append("  first_miss picked the wrong step")
    if cache_was_cold(mixed):
        failed.append("  a partially cached build was called cold")

    nothing_cached = [step(1, "FROM x", False), step(2, "COPY . .", False)]
    if not cache_was_cold(nothing_cached):
        failed.append("  a genuinely cold cache was not detected")

    total = len(STEP_NAMES) + len(NOT_STEPS) + 5
    for line in failed:
        print(line)
    print(f"{total - len(failed)}/{total} passed")
    assert not failed, f"{len(failed)} case(s) failed"


def test_build():
    run()


if __name__ == "__main__":
    run()
