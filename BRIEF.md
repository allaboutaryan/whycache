# whycache — project state

Working notes for anyone (human or agent) picking this up. The README is the
user-facing document; this one records what is done, what is deliberately not
done, and what would break if you changed it carelessly.

**Status:** Phases 0–3 complete. Installable, tested, verified against real
projects. Not yet published to PyPI, not yet pushed to GitHub.

---

## Layout

```
whycache/
  __init__.py      version
  __main__.py      python -m whycache
  cli.py           build runner, step parsing, blame, report
  dockerignore.py  .dockerignore matcher
  manifest.py      build-context fingerprinting, state, diff
test_dockerignore.py   18 checks
test_whycache.py       27 checks
test_e2e.py            7 checks, needs a Docker daemon
fixtures/          bad, modern, argchange, ignore-check
docs/demo.svg      README hero
```

`real/` holds cloned upstream repos used for verification and is gitignored.

## Verified behaviour

Eight cases, zero false accusations.

| Case | Expected | Result |
|---|---|---|
| psf/black, one commit | blame `.git/index`, warn not to ignore it | 11m00s, correct |
| sqlfluff, uncopied file | no miss at all | "Fully cached" |
| sqlfluff, `src/` file | blame `COPY src ./src`, not `pyproject.toml` | correct |
| whoami, `app.go` | `COPY . .`, step 7 | correct |
| whoami, `go.mod` | `COPY go.mod .`, step 4 | correct |
| argchange fixture | report the instruction diff | correct |
| modern fixture, `src/` | `final` stage, step 4 | correct |
| modern fixture, `requirements.txt` | `deps` stage, step 3 | correct |

Shapes covered: single-stage, multi-stage, named stages, `ARG`-templated base
images, `# syntax=` frontend, `RUN --mount=type=cache`, `COPY --from=`,
`FROM scratch`, whole-context `COPY . .`, and specific-path `COPY`.

## Things that will bite you

Every one of these was a real bug, found by running against real projects
rather than by reasoning.

1. **Multi-stage step names carry a stage prefix** (`[builder 3/7]`, not
   `[3/7]`). Miss that and the parser matches nothing, and the tool reports a
   five-minute build as "fully cached". `report()` now refuses to claim success
   when zero steps parsed — keep that guard.

2. **BuildKit emits vertexes in completion order**, and that order changes
   between runs. Order by start time, never by output position.

3. **`FROM` never reports `CACHED`** — base-image resolution is always `DONE`,
   so it always looks like a miss. It is skipped. The cost is that a genuinely
   changed base image is invisible; catching it needs a separate digest compare.

4. **Ignoring `.git/` breaks builds that read git metadata** (`hatch-vcs`,
   `setuptools-scm`, `versioningit`, `git describe`). `build_needs_git()` gates
   that suggestion. This is not theoretical — the tool broke psf/black's build
   with its own advice before the guard existed.

5. **A failed build still caches every step that completed** before the
   failure, so state must be saved even when `docker build` exits non-zero.
   Skip it and the baseline silently falls behind Docker's cache.

6. **Read the baseline before writing the new one.** An earlier version saved
   first and loaded second, so every run compared the new manifest against
   itself and reported "no context file changed" forever. Unit tests cannot
   catch this; `test_e2e.py` exists for that class of bug.

7. **"Nothing was cached" is not evidence of a cold cache.** A miss at the
   first step leaves nothing downstream that *could* be cached. Definite
   explanations (changed instruction, changed files) are checked first; cold
   cache is only the fallback.

8. **End-to-end tests must make a unique edit each run**, or Docker still holds
   a cache entry for the previous run's exact context and the "change" is
   legitimately a hit.

## Deliberate non-goals

- No Dockerfile editing. Report only.
- No LLM. This is a deterministic diff of two file lists.
- No CI integration, dashboard, or history graph yet.
- Silence over guessing: when the cause cannot be established, say so and name
  no file. A confidently wrong answer destroys the tool's reason to exist.

## Performance

Fingerprinting is per-file open cost, not hashing. Two fixes, both measured:
threads (file reads release the GIL) and skipping the read entirely when
`scandir` reports unchanged size and mtime.

| Context | Cold | Warm |
|---|---|---|
| 511 files / 8 MB | 1877 ms serial → 520 ms | — |
| 5955 files / 25 MB | 5853 ms | **727 ms** |

mtime is a shortcut for deciding whether to re-read a file. It is never what
decides whether a file *changed* — Docker ignores mtime, so the manifest does
too, and the self-check in `manifest.py` pins that.

## Left to do

- Publish to PyPI (needs the maintainer's token).
- Push to GitHub.
- Phase 4: run against ~10 popular repos, open `.dockerignore` PRs with the
  measured numbers, write up the findings.
