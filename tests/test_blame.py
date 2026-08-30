"""What gets blamed, and what must never be advised.

Two rules are pinned here. Only blame files the instruction actually copies,
and never suggest ignoring `.git/` on a project that reads git metadata to
build - the tool did exactly that to psf/black, and broke its build.

Run: python tests/test_blame.py   (or: pytest tests/test_blame.py)
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whycache.blame import blame, build_needs_git, copy_sources, noise_hits

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

NEEDS_GIT = [
    ("pyproject.toml", 'requires = ["hatch-vcs>=0.3.0"]', "pyproject.toml"),
    ("pyproject.toml", "[tool.setuptools_scm]", "pyproject.toml"),
    ("setup.py", 'use_scm_version=True, setup_requires=["setuptools-scm"]', "setup.py"),
    ("Dockerfile", "RUN git describe --tags > VERSION", "Dockerfile"),
    ("pyproject.toml", '[project]\nname = "plain"\nversion = "1.0"', None),
    ("Dockerfile", "FROM python:3.12\nCOPY . .", None),
]

NOISE = [
    # (changed paths, pattern expected in the suggestions)
    ([".git/index"], ".git/"),
    ([".git"], ".git/"),
    (["node_modules/react/index.js"], "node_modules/"),
    (["src/__pycache__/x.pyc"], "**/__pycache__/"),
    (["src/app.py"], None),
]


def run():
    failed = []

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
                failed.append(f"  build_needs_git({filename}, {content[:28]!r}) "
                              f"-> {got}, expected {expected}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    for paths, expected in NOISE:
        patterns = [p for p, _, _ in noise_hits(paths)]
        if expected is None and patterns:
            failed.append(f"  noise_hits({paths}) flagged {patterns}, expected none")
        elif expected is not None and expected not in patterns:
            failed.append(f"  noise_hits({paths}) -> {patterns}, expected {expected}")

    total = len(COPY_SOURCES) + len(BLAME) + len(NEEDS_GIT) + len(NOISE)
    for line in failed:
        print(line)
    print(f"{total - len(failed)}/{total} passed")
    assert not failed, f"{len(failed)} case(s) failed"


def test_blame():
    run()


if __name__ == "__main__":
    run()
