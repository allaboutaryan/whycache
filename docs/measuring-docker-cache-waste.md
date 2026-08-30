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

I read the `Dockerfile` and `.dockerignore` of 500 popular repositories
straight from the GitHub API — no clones, no builds — looking for one pattern:
a whole-context `COPY` with expensive work below it, and `.git` not excluded.

The sample is popular *deployable* software: projects tagged `docker`,
`kubernetes`, `self-hosted`, `devops`, `monitoring`, `database` and the like.
Sorting the most-starred repos by language instead returns mostly
awesome-lists and tutorials, which ship no container at all.

| | count | share |
|---|---|---|
| Repos read | 500 | |
| With a root `Dockerfile` | 151 | 30% |
| **Invalidating their cache on every commit** | **33** | **22%** |
| ...where the obvious fix breaks the build | 11 | 33% of those |
| ...where it is safe | 22 | 67% of those |

**One in five** containerised projects rebuilds from scratch every time someone
commits.

### Go is three times worse than everything else

| Language | With a Dockerfile | Wasting cache | |
|---|---|---|---|
| Go | 67 | 22 | **33%** |
| TypeScript | 23 | 2 | 9% |
| Python | 21 | 2 | 10% |
| JavaScript | 10 | 1 | 10% |

I did not expect that, and I do not think it is about Go being careless. The
canonical Go Dockerfile is four lines — `COPY . .`, `RUN go build` — and it
*works*. There is no `requirements.txt` step forcing you to think about what to
copy first, the way there is in Python or Node. The habit of splitting
`COPY go.mod go.sum` out ahead of `go mod download` is something you learn
after the build gets slow, not something the shape of the language suggests.

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

That is not a rare corner. Of the 33 repos wrecking their cache, **11 read git
metadata at build time** — `setuptools-scm`, `hatch-vcs`, `git describe` in a
Makefile. The obvious fix breaks a third of them, and the list is not obscure:
gitea, gogs, argo-cd, velero, atlantis, prometheus-operator.

If you take one thing from this, take that: before you add `.git` to a
`.dockerignore`, grep the project for `setuptools-scm`, `hatch-vcs`,
`versioningit`, `git describe`, and `git rev-parse`.

## What to do when the build does need git

Three options, cheapest first:

1. **Pass the version in as a build arg.** vitess already does this —
   `ARG BUILD_GIT_REV` — which is the right answer. (It still ships `.git`
   into the context, so it pays the cache cost for nothing. It is top of the
   safe-to-fix list for exactly that reason.)
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

**Caveats, honestly.** Only root-level `Dockerfile`s were read; plenty of
projects keep theirs under `build/` or `docker/` and were not counted, so the
real figure is a floor rather than a ceiling. The sample is popular deployable
software, not all software. Detection is static — a `COPY . .` above an
`apt-get install` is strong evidence of waste, not proof of it, and the three
repos I actually built are the ones I can vouch for. All timings come from one
Windows laptop; treat them as orders of magnitude. The survey script, its
response cache and the raw results are in the repo, so the numbers reproduce.
