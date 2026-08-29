# I measured Docker cache waste in 40 popular repos. The obvious fix breaks a third of them.

Docker tells you which build steps re-ran. It never tells you why. That gap is
small enough to ignore for years, and expensive enough to be worth a morning.

I got curious about how common the damage actually is, so I measured it.

## The mechanism, quickly

A Dockerfile is a sequence of cached steps. If step N is invalidated, **every
step after N re-runs**. So the cost of a cache miss is not the missed step — it
is everything below it.

Which makes this shape expensive:

```dockerfile
COPY . .                                  # invalidated by any file change
RUN apt-get install -y build-essential    # 40s
RUN pip install -r requirements.txt       # 3m
RUN make build                            # 1m
```

And this shape cheap:

```dockerfile
COPY requirements.txt .
RUN pip install -r requirements.txt       # protected
COPY . .                                  # nothing expensive below
```

Same instructions. Same image. Minutes apart on every rebuild.

The part nobody notices: `COPY . .` copies `.git` too. `.git` changes on
**every commit**. So on many projects, the mere act of committing invalidates
the build.

## What I measured

I pulled the `Dockerfile` and `.dockerignore` from 40 well-known repositories
and looked for one pattern: a whole-context `COPY` with expensive work below
it, and `.git` not excluded.

| | |
|---|---|
| Repos checked | 40 |
| With a root `Dockerfile` | 21 |
| Whole-context `COPY` above expensive steps | 6 |
| **No `.dockerignore` at all** | **3** |

Then I built the affected ones and made a single empty commit — no source
change, nothing but a commit — to see what that alone cost.

| Repo | Cache broke at | Cost of one commit |
|---|---|---|
| [psf/black](https://github.com/psf/black) | `COPY . /src/`, step 3 of 6 | **5m14s** |
| [traefik/whoami](https://github.com/traefik/whoami) | `COPY . .`, step 7 | 10.6s |
| [sqlfluff](https://github.com/sqlfluff/sqlfluff) | `COPY src ./src`, step 10 of 12 | 7.5s |

`black` is the one worth sitting with. Five minutes of rebuild, triggered by a
commit that changed no code the build cares about, on every single build.
Nobody there did anything wrong. It is simply invisible.

sqlfluff is the control case. It copies specific paths instead of the whole
tree, so its miss lands near the bottom and costs seconds. **The gap between five
minutes and seven seconds is the entire skill of writing a Dockerfile**, and
neither number is printed anywhere.

## The part I got wrong

The fix looks obvious. Add `.git` to `.dockerignore`. I wrote a tool that
suggested exactly that.

Then I followed my own advice on `black`, and the build failed.

`black` derives its version from git tags via `hatch-vcs`. Remove `.git` from
the build context and the version can no longer be computed, so `hatch build`
exits non-zero. The advice did not make the build slower. It made it **not
build**.

That is not a rare corner. Of the six repos where `.git` was wrecking the
cache, **three read git metadata at build time** — `hatch-vcs`,
`setuptools-scm`, and friends. The obvious fix breaks half of them.

If you take one thing from this, take that: before you add `.git` to a
`.dockerignore`, grep the project for `setuptools-scm`, `hatch-vcs`,
`versioningit`, `git describe`, and `git rev-parse`.

## What to do when the build does need git

Three options, cheapest first:

1. **Pass the version in as a build arg.** vitess already does this —
   `ARG BUILD_GIT_REV` — which is the right answer. (It still ships `.git`
   into the context, so it pays the cache cost for nothing. That one is a
   genuine easy win.)
2. **Copy `.git` in a later stage**, below the expensive steps, so it stops
   invalidating them.
3. **Compute the version outside the build** and write it to a file the
   Dockerfile copies.

## The boring conclusion

There is no clever insight here. Put the cheap, volatile things below the
expensive, stable ones, and keep out of the build context anything the build
does not read. Everyone knows this. Almost nobody measures whether their
Dockerfile actually does it, because Docker never shows you the number.

I built [whycache](https://github.com/allaboutaryan/whycache) to print that
number — which step missed, which file caused it, and what it cost. It is what
produced every measurement above.

```console
$ whycache .

X Cache broke at builder step 3:  COPY . /src/

  Reason - 1 file(s) changed in the build context:

    .git/index

  Cost - 5m14s of this 5m14s build.

  .git/ is breaking the cache, but do NOT ignore it:
    pyproject.toml reads git metadata at build time, so excluding
    .git/ makes the build fail rather than just slow.
```

That last paragraph exists because the tool broke `black`'s build before it
learned to say it.

---

**Caveats, honestly.** 40 repos is a sample, not a census, and it skews toward
infrastructure projects that happen to ship a root `Dockerfile` — plenty of
projects keep theirs elsewhere and were not counted. All timings are from one
laptop, so treat them as orders of magnitude, not benchmarks. The survey script
and the raw results are in the repo if you want to run it against your own set.
