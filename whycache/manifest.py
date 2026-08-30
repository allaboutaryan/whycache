"""Build-context fingerprints: hash, store, diff.

Two decisions here are load-bearing, both settled by the Phase 0 probe:

  * **Content only, never mtime.** `touch`ing a file without changing its
    bytes does not break Docker's cache (probe, build 3). Hashing mtime would
    make the tool cry wolf on every build.

  * **State lives outside the build context.** Writing into the context would
    change the context, which would break the cache — the tool would cause the
    very problem it reports.
"""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .dockerignore import Matcher

STATE_DIR = Path.home() / ".whycache"
CHUNK = 1 << 20


def _hash_file(path: Path) -> str:
    # ponytail: blake2b/8 is stdlib and fast; collisions here mean a missed
    # report, not a wrong one. Widen the digest if that ever shows up.
    h = hashlib.blake2b(digest_size=8)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _walk(root, ignore, _rel=""):
    """[(relative posix path, size, mtime_ns)] for every file Docker sends.

    Uses scandir so size and mtime come from the directory entry the OS
    already read, rather than a stat() call per file.
    """
    found = []
    try:
        entries = list(os.scandir(root / _rel if _rel else root))
    except OSError:
        return found

    for e in entries:
        rel = f"{_rel}/{e.name}" if _rel else e.name
        try:
            is_dir = e.is_dir(follow_symlinks=False)
        except OSError:
            continue
        if ignore.excluded(rel):
            # Pruning here is what keeps node_modules from being walked at all.
            continue
        if is_dir:
            found.extend(_walk(root, ignore, rel))
        else:
            try:
                st = e.stat(follow_symlinks=False)
                found.append((rel, st.st_size, st.st_mtime_ns))
            except OSError:
                found.append((rel, -1, -1))
    return found


def build_manifest(context_dir, prior=None):
    """-> ({path: content hash}, {path: [size, mtime_ns]})

    Hashing is the whole cost, and it is per-file open overhead rather than the
    hash itself: 5955 files / 25 MB took 20s serially on Windows — 3.5ms each —
    while blake2b runs at hundreds of MB/s. Two things fix that:

      * threads, because file reads release the GIL;
      * `prior`, which lets an unchanged file skip the open entirely.

    The hash, not the stat, is still what decides whether a file changed —
    Docker ignores mtime, so the manifest must too. size+mtime is only used to
    decide whether re-reading a file is worth it.

    ponytail: a file edited so that size *and* nanosecond mtime both land
    unchanged would be missed. Pass prior=None to force a full re-read.
    """
    root = Path(context_dir).resolve()
    ignore = Matcher.from_context(root)
    entries = _walk(root, ignore)

    old_hashes = (prior or {}).get("manifest", {})
    old_stats = (prior or {}).get("stat", {})

    manifest, stats, todo = {}, {}, []
    for rel, size, mtime in entries:
        stats[rel] = [size, mtime]
        known = old_stats.get(rel)
        if known and list(known) == [size, mtime] and rel in old_hashes:
            manifest[rel] = old_hashes[rel]
        else:
            todo.append(rel)

    def one(rel):
        try:
            return rel, _hash_file(root / rel)
        except OSError:
            # unreadable file: record its absence of hash rather than crash
            return rel, "?"

    if len(todo) < 32:
        manifest.update(one(p) for p in todo)
    else:
        workers = min(32, (os.cpu_count() or 4) * 4)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            manifest.update(pool.map(one, todo))

    return manifest, stats


def _state_path(context_dir) -> Path:
    root = str(Path(context_dir).resolve())
    key = hashlib.blake2b(root.encode("utf-8"), digest_size=8).hexdigest()
    return STATE_DIR / f"{key}.json"


def load_state(context_dir) -> dict | None:
    p = _state_path(context_dir)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_state(context_dir, state: dict) -> None:
    p = _state_path(context_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=1), encoding="utf-8")


def diff(old: dict, new: dict) -> dict:
    """What changed between two manifests."""
    o, n = set(old), set(new)
    return {
        "added": sorted(n - o),
        "removed": sorted(o - n),
        "changed": sorted(k for k in o & n if old[k] != new[k]),
    }

