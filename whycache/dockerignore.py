"""`.dockerignore` matching.

Getting this wrong makes the tool blame a file Docker never looked at, so it
is the first thing built and the first thing tested.

Docker's rules (moby/patternmatcher), which are *not* gitignore's:
  - one pattern per line; blank lines and `#` comments ignored
  - patterns are always relative to the context root, so a leading `/` is noise
  - `!` re-includes; **the last matching pattern wins**, so order matters
  - `*` and `?` stop at `/`; `**` crosses directory boundaries
  - excluding a directory excludes everything under it
"""

import re
from pathlib import PurePosixPath


def _to_regex(pattern: str) -> re.Pattern:
    """Translate one Docker ignore pattern into an anchored regex."""
    out = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    # `**/x` must also match a bare `x` at the root
                    out.append("(?:.*/)?")
                    i += 1
                else:
                    out.append(".*")
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


class Matcher:
    """Decides whether a context-relative path is excluded from the build."""

    def __init__(self, text: str = ""):
        self.rules = []  # (regex, negated)
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:].strip()
            # leading and trailing slashes carry no meaning here
            line = line.strip("/")
            if not line:
                continue
            self.rules.append((_to_regex(line), negated))

    @classmethod
    def from_context(cls, context_dir):
        f = PurePosixPath(str(context_dir)) / ".dockerignore"
        try:
            with open(f, encoding="utf-8") as fh:
                return cls(fh.read())
        except (FileNotFoundError, NotADirectoryError):
            return cls("")

    def excluded(self, path: str) -> bool:
        """`path` is context-relative, POSIX separators, no leading slash.

        A path is excluded if it matches, or if any ancestor directory does.
        Last matching rule wins, so `!` can re-include.
        """
        path = path.strip("/")
        parts = path.split("/")
        candidates = ["/".join(parts[: i + 1]) for i in range(len(parts))]

        verdict = False
        for regex, negated in self.rules:
            if any(regex.match(c) for c in candidates):
                verdict = not negated
        return verdict


if __name__ == "__main__":
    m = Matcher("*.log\n!keep.log\n")
    assert m.excluded("a.log") and not m.excluded("keep.log")
    print("ok — run test_dockerignore.py for the full set")
