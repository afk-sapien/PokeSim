# Publishing a release

The release workflow publishes Python packages, a Linux amd64 and arm64 image at
`ghcr.io/afk-sapien/pokesim:<version>`, and versioned Compose downloads.
Standalone executables and app bundles are excluded. Each architecture's image archive
remains available as a checksummed release download for offline loading.

## Trigger and checks

Ordinary branch pushes and pull requests do not publish anything. When ready to
release, run `python tools/release.py version <version>`. It moves every pinned
version together: `pyproject.toml`, the lockfile, both installers, the Dockerfile, the
Compose files including `compose.quickstart.yaml`, `.env.example`, and the install
commands in the docs. Then run `uv lock --check`, write the release notes and write the
version's changelog section. CI and the
release workflow both fail while any pin differs from the package version, so a missed
file cannot ship. Commit and merge the reviewed changes to `main`. Push a new `v<version>` tag for that exact commit, then
create a draft release and start the publishing workflow:

```sh
git tag v0.7.0
git push origin v0.7.0
gh release create v0.7.0 --verify-tag --draft --title "PokeSim 0.7.0" --notes-file docs/release-notes.md
gh workflow run release.yml --ref main -f tag=v0.7.0
```

Use the actual next version when following these examples. A tag push alone does
not publish anything. The tag must match the package version and release notes heading.
Only draft releases can be built. The workflow publishes the draft after every upload
has been verified, so `/releases/latest/download/` continues to serve the previous
completed stable release throughout validation. Public installation commands use those
release asset URLs rather than files from `main`.

### The changelog

Pull requests do not edit `CHANGELOG.md`. Each one says in its description what a user sees.
The release pull request turns `## Unreleased` into `## <version>`, keeps the entries already
there and adds one for each user-visible pull request merged since the last tag that has none yet:

```sh
gh pr list --state merged --base main --limit 300 --json number,title,body,mergedAt \
  --search "merged:>$(git log -1 --format=%cI v0.7.0)"
```

An entry says what changed for a player, a host or a contributor, and why, in the voice of
the entries already there. A pull request none of them would notice gets no entry.

To retry a failed run, start the workflow manually with the unchanged draft's tag.
It refuses a version whose final image download is already attached, so inspect a
failure during the final upload before retrying. Never move a published tag.

The workflow does not repeat the verification matrix. The CI and Python install
workflows run the full matrix on every tag, every night and when started by hand. A pull
request or a push to `main` runs Linux x86 and Python 3.12 only, so the tag's own runs are
the ones that pass the gate. The `gate` job runs
`tools/release.py check-gates` and requires push runs of both workflows for the exact
release commit in which every job succeeded, every required job is present by its exact
name, and none was skipped or cancelled. Required jobs are the whole CI workflow (lint, the
dependency audit, tests on Python 3.11, 3.12 and 3.14, the four browser shards, and both
container jobs) and the whole Python install workflow (the native test shards on Linux x86
and ARM, macOS Intel and ARM and all four Windows shards, the fresh installs on the same
platforms, and the acceleration job). The job list in `tools/release.py` is
compared with the workflow files by `tests/test_release_gates.py`, so adding, renaming or
removing a job in a workflow fails the tests until the gate agrees. The gate waits for runs
that are still in progress, up to 35 minutes, and fails for a missing or failed run. The
slim run from the push to `main` lacks the full matrix and never passes the gate alone, so
the tag must be pushed before the workflow starts. The script comes from the commit that
dispatched the workflow, not from the release revision.

The `build` job runs in parallel with the gate, once per architecture on a native runner
(`ubuntu-latest` for amd64, `ubuntu-24.04-arm` for arm64). The amd64 leg also builds and
checks the wheel and source package. Each leg builds and tests its image and keeps it as a
workflow artifact. The `rehearse` job assembles the downloads from both. These jobs have
read-only permissions and publish nothing. The `publish` job runs only after the gate, the
builds and the rehearsal succeed. It is the only job that can push an image or change a
release. It loads the tested images, logs in to GHCR with the repository's temporary
`GITHUB_TOKEN`, pushes each one as `<version>-linux-<arch>`, and joins them into the
multi-platform `<version>` tag. It then checks anonymously that the tag serves exactly
amd64 and arm64 and that each platform pulls the tested image. No personal access token or added
repository secret is needed. The publishing job has `packages: write` and
`contents: write`. Draft validation also needs `contents: write` because GitHub only
exposes draft releases to identities with push access. All other jobs retain read-only access.

To rehearse the whole workflow without publishing, start it with the dry run input:

```sh
gh workflow run release.yml --ref main -f tag=v0.7.0 -f dry_run=true
```

A dry run validates the tag, runs the gate, and runs the full build and image checks. The
`publish` job is skipped, so no image is pushed and no release is uploaded or edited. A dry run
does not require a draft release, so it can also run against a tag that is already published.

It next pulls the image using an empty Docker credentials directory and verifies
that each platform has the same creation time, layers and labels as the tested build.
The image ID is not compared, because the containerd image store reports the digest
of the pulled tag there. Release assembly records the
registry digest, image ID, source revision, platform, and file checksums.
`compose.yaml`, `compose.quickstart.yaml`, and `env.example` select the exact image version.
The `install.sh` and `install.ps1` downloads select the matching wheel version and are
included in the checksums. The Python matrix exercises both installer scripts on their
respective platforms, including repeat installation. The container checks exercise a
fresh named volume and verify that it survives container removal and recreation. The workflow uploads the
downloads to the release and verifies every uploaded checksum. Versions containing
`rc` are marked as prereleases. After publication, `tools/release.py floating-tags` moves
`latest` to the newest stable release and `<major>.<minor>`, such as `0.5`, to the newest
stable release of its line. A fix to an older line moves only that line, and release
candidates move neither. Each moved tag is pulled anonymously and checked against the tested image.

After each publication, move `main` to the next development version, such as
`python tools/release.py version 0.7.0.dev0`. A development version moves only
`pyproject.toml`, `pokesim/__init__.py`, the lockfile and the Dockerfile, so builds from
`main` report it. The installers, Compose files and docs keep naming the published
release, and the pin check requires them to agree on it.

## Emulator dependencies are GitHub release wheels

PokeSim depends on `pokecore` and `pyboy-rs`, which are not on PyPI. `pyproject.toml` names
their release wheels directly, each with a `#sha256=` fragment that pip and uv verify, so the PokeSim
wheel's metadata resolves for uv, pip and pipx without a Rust toolchain, and `uv.lock` records the same
hashes. pyboy-rs has one abi3 wheel per supported platform (Linux x86-64 and aarch64, macOS x86-64 and
arm64, Windows x86-64), selected by markers. Core carries the union of those markers as well. Without
that, Core's own requirement on `pyboy-rs` would make pip ask PyPI for the name on a platform with no
wheel (Windows ARM64, 32-bit ARM, FreeBSD), which is a dependency confusion risk. On those platforms
nothing is installed from either name, and the installers and the application say so. Musl Linux
(Alpine) matches the Linux markers but has no compatible wheel, so pip stops with a wheel error, and
`install.sh` refuses it up front. PyPI names must never be relied on: `pip install pokesim` installs an
unrelated project, and the docs and installers never suggest it.

The `pokecore` source lives in `packages/pokecore` as a uv workspace member, so `uv.lock`, a checkout and
the container build use that source and the lock holds no pokecore wheel. The URL pin is what pip users
get. The pin check requires it to name the member's version and, with `--remote`, to serve a wheel whose
files equal the member's source. See [Shared game core](shared-core.md).

Before tagging PokeSim, the pyboy-rs release and the pokecore release it pins must exist with their wheels
attached. The pyboy-rs release must also carry its source archive, which the Dockerfile fetches with a
required `EMULATOR_SOURCE_SHA256`. The pokecore release workflow never modifies a published release, and the
pyboy-rs one should refuse `--clobber` the same way, so a published asset can never change under a recorded
hash. PokeSim's own check is that every asset hash in `uv.lock`, and the pokecore pin's fragment, equals the
hash of the file the release serves.

### pokecore releases

A PokeSim release that ships a Core change first cuts a pokecore release of this repository from
`packages/pokecore`. Its tag is `pokecore-v<version>`, it carries the wheel, the sdist and `SHA256SUMS.txt`,
and it never becomes the latest release, so `/releases/latest/` keeps serving PokeSim.

1. In a pull request, bump `version` in `packages/pokecore/pyproject.toml` and `__version__` in
   `packages/pokecore/src/pokecore/__init__.py`, and add a `## <version>` section to
   `packages/pokecore/CHANGELOG.md`. Merge it.
2. Tag that commit on `main` and start the workflow. Add `-f dry_run=true` to do everything except the release.

   ```sh
   version=0.11.1
   git tag "pokecore-v$version"
   git push origin "pokecore-v$version"
   gh workflow run pokecore-release.yml --ref main -f tag="pokecore-v$version"
   ```

3. The workflow checks the tag against both versions, the changelog section and that `main` holds the commit.
   It runs the pokecore suite on Python 3.11, 3.12 and 3.14 with no skips, builds both files, installs each
   alone, and compares the wheel with the member source. It publishes the draft only after the attached files
   download with the hashes in `SHA256SUMS.txt`.
4. In the PokeSim release pull request, run `python tools/release.py pin-pokecore <version>`. It refuses a wheel whose
   hash is not the listed one or whose files differ from `packages/pokecore/src/pokecore`, and rewrites only
   the pin's URL and fragment. `uv.lock` does not change.
5. The release workflow's `tools/release.py check-pins --remote` repeats that comparison, so a PokeSim tag
   cannot ship a pin whose wheel differs from `packages/pokecore`.

### Temporary pins and how they are finalized

While the upstream releases do not exist, one commit marked TEMP points the pins at copies in
`tools/temp-wheels/` (see `TEMP_REMOVE_BEFORE_RELEASE.md`). Those pins must not reach a tag.
`tools/release.py check-pins` fails if any of these remain: a URL containing `refs/heads/` or
`temp-wheels`, the `tools/temp-wheels/` directory, `TEMP_REMOVE_BEFORE_RELEASE.md`, a TEMP comment in the
Dockerfile, a pyproject URL without a `#sha256=` fragment equal to the locked hash, an empty or malformed
`EMULATOR_SOURCE_SHA256`, or a source archive name that differs from the locked pyboy-rs version. The
release workflow runs it in the `validate` job (with `--remote`, which also downloads every locked
emulator asset and the source archive and compares their SHA-256 with `uv.lock` and the Dockerfile) and
the `gate` job runs the local half against the release revision. A dry run fails the same way.

To finalize, once both upstream releases are public:

1. Write a manifest of the final asset URLs and hashes (see `python tools/release.py finalize-pins --help`).
   The asset names are the same wheels as the temporary copies.
2. `python tools/release.py finalize-pins manifest.json` rewrites `pyproject.toml` (final URLs with
   `#sha256=` fragments, no temp-wheels `[tool.uv.sources]` entry), `uv.lock` (URL sources and
   hashes), and the Dockerfile (source archive URL and checksum, no temp-wheels COPY), removes the TEMP
   comments, and deletes `tools/temp-wheels/` and `TEMP_REMOVE_BEFORE_RELEASE.md`. It re-checks its own
   result and, if anything is left over, puts every file back and fails.
3. `uv lock --check` confirms the lock still matches. Run `uv lock` if the upstream metadata changed.
4. `python tools/release.py check-pins --remote` downloads the published assets and compares hashes.
5. Commit, let CI pass on the release commit, then tag.

Reverting the TEMP commit and running `uv lock` is the equivalent manual route. After either route,
`tests/test_release_pins.py` still passes because it builds its own trees.

## First publication: package visibility

GitHub creates a new GHCR package as private, even for a public repository.
After the first image push, open the account's **Packages**, select **pokesim**,
open **Package settings**, and change its visibility to **Public**. Confirm that
the package is linked to this repository and that the repository has Actions
access. See [GitHub's package visibility instructions](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility).

The first run will stop at anonymous pull verification until that visibility
setting is public. Set it once, then rerun the workflow for the same tag. Subsequent
versions of the public package retain its visibility and publish automatically.
Nothing needs to be uploaded now to prepare this workflow. Repository or account
policies that prohibit package creation must be resolved before the first release.

## Failed runs and retries

A failed gate or build leaves GHCR unchanged and the GitHub
release remains a private draft. The previous completed stable release stays latest. Once the image has been pushed, a later
failure can leave that image in GHCR with an incomplete draft asset list. Inspect the
failure and rerun the workflow manually against the same unchanged tag. It replaces
partial assets and checks the complete asset set. Never move a published tag. Fix
released software in a new version.

Before each push, the publish job refuses to replace a version tag that already
serves a different image, so a rerun can never change what a version tag serves.
A fresh build is not byte-identical, so a rerun after the image was pushed must
publish the earlier run's tested images:

```sh
gh workflow run release.yml --ref main -f tag=v0.7.0 -f images_from_run=<run id>
```

The publish job checks that those images were built from the tag's revision. Its
registry checks come from the dispatching commit, so a fix to a check reaches a
rerun of an unchanged tag. Workflow artifacts expire after three days. Past that,
publish a new version. Published releases
are rejected before the build, so this workflow does not overwrite their images.
Existing installations keep their selected version until their owners upgrade.

## Local checks without publishing

```sh
uv run --locked pytest -q tests/test_release_assembly.py tests/test_registry_image.py
uv run --locked python tools/check_docs.py
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example -f compose.yaml -f compose.build.yaml config --quiet
```

These commands do not push images, create tags, dispatch workflows, or publish
releases. Native ARM64 images would require additional build and runtime validation
before adding them to this pipeline.
