"""Checks for the parsing that decides what gets blamed.

The step-name regex is the piece that once made a 5-minute multi-stage build
report as "fully cached", so it is pinned here.

Run: python test_whycache.py   (or: pytest test_whycache.py)
"""

import shutil
import tempfile
from pathlib import Path

from whycache.cli import RE_STEP, blame, build_needs_git, copy_sources

# Suggesting `.dockerignore: .git/` to a project that reads git metadata at
# build time does not slow the build down — it breaks it. This is not
# hypothetical: the tool did exactly that to psf/black.
NEEDS_GIT = [
    ("pyproject.toml", 'requires = ["hatch-vcs>=0.3.0"]', "pyproject.toml"),
    ("pyproject.toml", '[tool.setuptools_scm]', "pyproject.toml"),
    ("setup.py", 'use_scm_version=True, setup_requires=["setuptools-scm"]', "setup.py"),
    ("Dockerfile", 'RUN git describe --tags > VERSION', "Dockerfile"),
    ("pyproject.toml", '[project]\nname = "plain"\nversion = "1.0"', None),
    ("Dockerfile", 'FROM python:3.12\nCOPY . .', None),
]

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

COPY_SOURCES = [
    ("COPY . .", ["."]),
    ("COPY requirements.txt .", ["requirements.txt"]),
    ("COPY src/ pkg/ /app/", ["src/", "pkg/"]),
    ("COPY --from=builder /opt/venv /opt/venv", ["/opt/venv"]),
    ("ADD archive.tar /out", ["archive.tar"]),
    ("RUN pip install -r requirements.txt", None),
    ("WORKDIR /app", None),
]

BLAME = [
    # (changed files, copy sources, expected blamed)
    (["src/a.py", "docs/b.md"], ["."], ["src/a.py", "docs/b.md"]),
    (["src/a.py", "docs/b.md"], ["src"], ["src/a.py"]),
    (["requirements.txt", "src/a.py"], ["requirements.txt"], ["requirements.txt"]),
    (["src/a.py"], ["requirements.txt"], []),
    (["src/deep/c.py"], ["src/"], ["src/deep/c.py"]),
]


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

    for instr, expected in COPY_SOURCES:
        got = copy_sources(instr)
        if got != expected:
            failed.append(f"  copy_sources({instr!r}) -> {got}, expected {expected}")

    for changed, sources, expected in BLAME:
        got = blame(changed, sources)
        if got != expected:
            failed.append(f"  blame({changed}, {sources}) -> {got}, expected {expected}")

    for filename, content, expected in NEEDS_GIT:
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / filename).write_text(content, encoding="utf-8")
            got = build_needs_git(tmp)
            if got != expected:
                failed.append(f"  build_needs_git({filename}, {content[:32]!r}) "
                              f"-> {got}, expected {expected}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    total = (len(STEP_NAMES) + len(NOT_STEPS) + len(COPY_SOURCES) + len(BLAME)
             + len(NEEDS_GIT))
    for line in failed:
        print(line)
    print(f"{total - len(failed)}/{total} passed")
    assert not failed, f"{len(failed)} case(s) failed"


def test_whycache():
    run()


if __name__ == "__main__":
    run()
