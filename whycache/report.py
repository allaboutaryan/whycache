"""Turning a diagnosis into something a person can act on."""

import sys

from .blame import noise_hits
from .build import real_steps


def _encodable(text):
    """Windows consoles default to cp1252 and blow up on box-drawing glyphs."""
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


HIT, MISS = ("✓", "✗") if _encodable("✓✗") else ("OK", "X")


def human(secs):
    if secs < 60:
        return f"{secs:.1f}s"
    return f"{int(secs // 60)}m{int(secs % 60):02d}s"


def report(steps, miss, changed, cold, have_baseline, git_needed=None,
           prev_instr=None):
    # Parsing nothing must never be reported as success. A silent zero here is
    # how the tool once called a five-minute multi-stage build "fully cached".
    if not steps:
        print("\n? Could not read any build steps from Docker's output.")
        print("  Not reporting a result rather than guessing at one.\n")
        return

    total = sum(s["secs"] or 0 for s in steps)

    if miss is None:
        print(f"\n{HIT} Fully cached. Build took {human(total)}.\n")
        return

    # Everything downstream of a miss re-runs, and in a multi-stage build that
    # spans stages - so the wasted work is simply every step that re-ran.
    wasted = sum(s["secs"] or 0 for s in real_steps(steps) if not s["cached"])

    where = (f"{miss['stage']} step {miss['idx']}" if miss["stage"]
             else f"step {miss['idx']}")
    print(f"\n{MISS} Cache broke at {where}:  {miss['instr'][:70]}\n")

    # Order matters. "Nothing was cached" is what an early miss looks like from
    # the outside - a miss at the first step leaves nothing downstream that
    # *could* be cached - so treating it as a cold cache up front suppresses the
    # real, known answer. Definite explanations first; cold cache only as the
    # fallback when nothing else explains it.
    if not have_baseline:
        print("  Baseline saved. Change something and run again to see the cause.\n")
        return

    if prev_instr:
        print("  Reason - the instruction itself changed since the last build:\n")
        print(f"    was:  {prev_instr[:66]}")
        print(f"    now:  {miss['instr'][:66]}")
        print("\n  A changed build arg or env var shows up here, because Docker")
        print("  substitutes them into the command before caching it.")
        print(f"\n  Cost - {human(wasted)} of this {human(total)} build.\n")
        return

    if not changed:
        if cold:
            print("  Cache was cold - nothing was cached, so no file is responsible.")
            print("  (Pruned cache, a fresh builder, or --no-cache.)\n")
        else:
            print("  No context file changed, and this step's command is unchanged.")
            print("  The cause is upstream of the build context - most likely a")
            print("  --build-arg, a --secret or --mount, or a moved base image tag.\n")
        return

    print(f"  Reason - {len(changed)} file(s) changed in the build context:\n")
    for p in changed[:12]:
        print(f"    {p}")
    if len(changed) > 12:
        print(f"    ... and {len(changed) - 12} more")

    print(f"\n  Cost - {human(wasted)} of this {human(total)} build.")

    hits = noise_hits(changed)
    safe = [h for h in hits if not (h[0] == ".git/" and git_needed)]
    risky = [h for h in hits if h[0] == ".git/" and git_needed]

    if safe:
        print("\n  Fix - add to .dockerignore:")
        for pattern, reason, n in safe:
            print(f"    {pattern:<22} ({reason}, {n} file(s))")
        print(f"\n  Saves ~{human(wasted)} per build.")

    for _, _, n in risky:
        print(f"\n  .git/ is breaking the cache ({n} file(s)), but do NOT ignore it:")
        print(f"    {git_needed} reads git metadata at build time, so excluding")
        print("    .git/ makes the build fail rather than just slow.")
        print("    Pass the version in as a build arg instead, or copy .git in a")
        print("    later stage so it stops invalidating the expensive steps.")
    print()
