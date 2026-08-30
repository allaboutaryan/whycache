"""Build-context fingerprinting.

Two properties matter and are pinned here. `.dockerignore` must be honoured
before anything is hashed, and mtime must never reach the manifest - Docker
ignores mtime for its cache, so a tool that watches it cries wolf on every
build.

Run: python tests/test_manifest.py   (or: pytest tests/test_manifest.py)
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from whycache.manifest import build_manifest, diff


def run():
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "src").mkdir()
        (tmp / "src" / "app.py").write_text("v1")
        (tmp / "keep.txt").write_text("hello")
        (tmp / "debug.log").write_text("noise")
        (tmp / "node_modules").mkdir()
        (tmp / "node_modules" / "big.js").write_text("x" * 1000)
        (tmp / ".dockerignore").write_text("*.log\nnode_modules\n")

        m1, st1 = build_manifest(tmp)
        assert "src/app.py" in m1, m1
        assert "debug.log" not in m1, "ignored file was hashed"
        assert "node_modules/big.js" not in m1, "ignored dir was walked"

        os.utime(tmp / "src" / "app.py", (0, 0))
        assert build_manifest(tmp)[0] == m1, "mtime leaked into the manifest"

        prior = {"manifest": m1, "stat": st1}
        assert build_manifest(tmp, prior)[0] == m1, "stat shortcut changed the manifest"

        (tmp / "src" / "app.py").write_text("v2")
        m2, _ = build_manifest(tmp, prior)
        d = diff(m1, m2)
        assert d["changed"] == ["src/app.py"], d
        assert not d["added"] and not d["removed"], d

        print("6/6 passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_manifest():
    run()


if __name__ == "__main__":
    run()
