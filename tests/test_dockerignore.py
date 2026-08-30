"""The check that fails if `.dockerignore` matching breaks.

Run: python test_dockerignore.py   (or: pytest test_dockerignore.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whycache.dockerignore import Matcher

CASES = [
    # (name, dockerignore text, path, expected_excluded)
    ("plain name", "node_modules", "node_modules", True),
    ("dir contents", "node_modules", "node_modules/react/index.js", True),
    ("unrelated untouched", "node_modules", "src/app.js", False),
    ("glob stops at slash", "*.log", "debug.log", True),
    ("glob does not cross dirs", "*.log", "logs/debug.log", False),
    ("doublestar crosses dirs", "**/*.log", "a/b/debug.log", True),
    ("doublestar matches at root", "**/*.log", "debug.log", True),
    ("negation re-includes", "*.md\n!README.md", "README.md", False),
    ("negation leaves others", "*.md\n!README.md", "CHANGELOG.md", True),
    ("order wins: exclude last", "!README.md\n*.md", "README.md", True),
    ("comments ignored", "# node_modules\nsrc", "node_modules", False),
    ("blank lines ignored", "\n\n*.log\n\n", "x.log", True),
    ("leading slash is noise", "/build", "build/out.js", True),
    ("trailing slash is noise", "build/", "build/out.js", True),
    ("question mark is one char", "file?.txt", "fileA.txt", True),
    ("question mark not two", "file?.txt", "fileAB.txt", False),
    ("dotfile dir", ".git", ".git/index", True),
    ("nested negation", "logs\n!logs/keep.log", "logs/keep.log", False),
]


def run():
    failed = []
    for name, text, path, expected in CASES:
        got = Matcher(text).excluded(path)
        if got != expected:
            failed.append(f"  {name}: {path!r} -> {got}, expected {expected}")
    for line in failed:
        print(line)
    print(f"{len(CASES) - len(failed)}/{len(CASES)} passed")
    assert not failed, f"{len(failed)} dockerignore case(s) failed"


def test_dockerignore():
    run()


if __name__ == "__main__":
    run()
