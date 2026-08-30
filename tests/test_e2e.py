"""End-to-end check against a real Docker build. Requires a running daemon.

Unit tests cannot catch wiring bugs. The one that hurt most was reading the
saved baseline *after* overwriting it, which made every run report "no context
file changed" — each unit passed, the tool was useless, and it took two
multi-minute builds to notice. This sequence catches that class of bug.

Run: python test_e2e.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
import time
import sys
from pathlib import Path

HERE = Path(__file__).parent
FIXTURE = HERE / "fixtures" / "bad"
APP = FIXTURE / "src" / "app.py"


def whycache():
    p = subprocess.run([sys.executable, "-m", "whycache", str(FIXTURE)],
                       capture_output=True, text=True, cwd=HERE)
    assert p.returncode == 0, f"whycache failed:\n{p.stdout}\n{p.stderr}"
    return p.stdout


def run():
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"
    (FIXTURE / ".dockerignore").unlink(missing_ok=True)
    original = APP.read_bytes()
    checks = []

    try:
        whycache()                                    # establish a baseline
        out = whycache()
        checks.append(("unchanged rebuild is fully cached",
                       "Fully cached" in out))

        # The edit must be unique per run. Writing the same bytes every time
        # leaves Docker holding a cache entry for that exact context from the
        # previous run, so the "change" is legitimately a cache hit and the
        # test fails against a perfectly correct tool.
        APP.write_bytes(original + f'\nprint("e2e {time.time_ns()}")\n'.encode())
        out = whycache()
        checks.append(("a real change is reported as a miss",
                       "Cache broke" in out))
        checks.append(("the changed file is named",
                       "src/app.py" in out))
        checks.append(("unrelated files are not blamed",
                       "requirements.txt" not in out))
        checks.append(("a cost is attributed",
                       "Cost -" in out))
        checks.append(("source code is not called ignorable",
                       "add to .dockerignore" not in out))

        out = whycache()
        checks.append(("returns to fully cached once settled",
                       "Fully cached" in out))
    finally:
        APP.write_bytes(original)

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    assert not failed, f"{len(failed)} end-to-end check(s) failed"


def test_e2e():
    run()


if __name__ == "__main__":
    run()
