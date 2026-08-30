"""Command line entry point: wire the pieces together, own no logic."""

import sys
from pathlib import Path

from .blame import blame, build_needs_git, copy_sources, previous_instr
from .build import cache_was_cold, first_miss, run_build, steps_of
from .manifest import build_manifest, diff, load_state, save_state
from .report import report

USAGE = "usage: whycache [context-dir] [-- extra docker build args]"


def main(argv):
    args = argv[1:]
    extra = []
    if "--" in args:
        i = args.index("--")
        args, extra = args[:i], args[i + 1:]

    if args and args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    context = Path(args[0] if args else ".").resolve()
    if not (context / "Dockerfile").exists():
        print(f"No Dockerfile in {context}\n{USAGE}", file=sys.stderr)
        return 2

    # Read the baseline before anything can overwrite it. Saving first and
    # loading second makes every run compare the manifest against itself.
    old = load_state(context)
    have_baseline = old is not None

    new_manifest, new_stats = build_manifest(context, old)
    rc, vertexes, out = run_build(context, extra)
    steps = steps_of(vertexes)

    # A failed build still caches every step that completed before the failure,
    # so Docker's cache moves forward even when the build does not. Skipping
    # the save here leaves our baseline behind Docker's, and the next run then
    # reports "no context file changed" for a context that really did change.
    save_state(context, {"manifest": new_manifest, "stat": new_stats,
                         "steps": [{"stage": s["stage"], "idx": s["idx"],
                                    "instr": s["instr"]} for s in steps]})

    if rc != 0:
        print(out[-2000:], file=sys.stderr)
        print("\ndocker build failed - nothing to explain.", file=sys.stderr)
        return rc

    miss = first_miss(steps)
    changed = []
    if miss and have_baseline:
        d = diff(old.get("manifest", {}), new_manifest)
        changed = blame(sorted(d["added"] + d["removed"] + d["changed"]),
                        copy_sources(miss["instr"]))

    report(steps, miss, changed,
           cold=cache_was_cold(steps),
           have_baseline=have_baseline,
           git_needed=build_needs_git(context),
           prev_instr=previous_instr(miss, (old or {}).get("steps")) if miss else None)
    return 0


def cli():
    """Console-script entry point."""
    sys.exit(main(sys.argv))
