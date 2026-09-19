# Historical distribution readiness review

This review predates the repository consolidation. Its branch names, commits,
blockers, and standalone-download recommendations describe that earlier snapshot.
See [current release status](../RELEASE_STATUS.md) for the present plan.

Reviewed September 18, 2026. Scope: public GitHub repository, published assets,
local packaging, CI, desktop onboarding, and home-server installation.

PokeSim has the foundations for a public beta. The main launch blockers are the
outdated public default branch, a demanding server installation path, and separate
desktop and server publication processes. Prioritize those before adding more
distribution channels.

## Evidence and scope

The local checkout is `codex/adventure-progress` at `6570c41`. It contains rc31
and pre-existing uncommitted dashboard work. GitHub's default branch is `main`
at `10c4300`, which still declares rc6. The development branch is 79 commits
ahead of `main`. These are live GitHub observations, not stale remote-tracking refs.
See the [branch comparison](https://github.com/afk-sapien/PokeSim/compare/main...codex/adventure-progress).

The [rc31 prerelease](https://github.com/afk-sapien/PokeSim/releases/tag/v0.2.0rc31)
is public and has five desktop archives, Python wheel and source packages, an
amd64 container archive, Compose configuration, and checksums. Desktop downloads
are about 40 to 75 MB. The container archive is about 202 MB. The recorded
[release receipt](validation/release-0.2.0rc31.json) identifies its source as
`0983b0d`. All five jobs in the subsequent
[desktop workflow for this checkout](https://github.com/afk-sapien/PokeSim/actions/runs/35045829185)
also succeeded.

The initial findings below describe the state before this pass. The implementation
section records subsequent changes. This pass did not merge branches, change GitHub
settings, or publish artifacts.

## Implemented in this pass

- Reworked the README around direct native downloads and the published Docker guide.
  Removed the misleading unqualified source clone. The prebuilt server guide now
  downloads Compose and environment files directly, without cloning PokeSim.
- Added `pokesim-prepare-data --download` and `--reference-archive`. The updated source
  Compose setup uses verified archive preparation, reuses valid data offline, and
  preserves the original Git-checkout command. Published rc31 instructions remain
  separate because the released image does not have the new CLI options.
- Made native desktop builds reusable from the release workflow. Publication waits
  for all five targets, checks package and container identities, gathers every asset,
  writes unified checksums, verifies draft uploads, and then publishes.
- Added extracted desktop archive checks, a fresh installed-wheel launcher smoke,
  bounded Compose setup and save/resume checks using PyBoy's demo ROM, and tests for
  incomplete or mismatched releases. Package checks now require both Python archives.
- Added bounded CI jobs and cancellation of superseded CI runs.

Still needed: review and merge the intended baseline into `main`, publish and verify
anonymous registry images, qualify server ARM64, simplify volume ownership, sign
desktop applications, and collect longer hardware and gameplay measurements.
The updated workflow must pass on GitHub before the next release is qualified.

## What is already strong

- Native desktop builds cover Windows x86-64, both Mac architectures, and Linux
  x86-64 and ARM64. Bundled-runtime checks exercise PyBoy's demonstration ROM.
- Desktop setup already accepts the user's ROM and downloads a verified reference
  archive without Git. Prepared adventures can start offline.
- Dependencies are locked for the normal source and container paths. Actions are
  pinned to commits, and Dependabot covers Actions, Docker, and uv.
- Containers run as an unprivileged user. Compose limits filesystem writes,
  capabilities, and log growth, with a read-only ROM mount.
- Tests cover browser flows, process locking, shutdown failures, and persistence.
  Packages include build identity and check for required assets and excluded data.
- Backup, restore, rollback, licensing, and experimental gameplay limits are documented.

## Findings before implementation

| Priority | Finding | User impact | Recommended result |
| --- | --- | --- | --- |
| Before promotion | Default branch still presents rc6 | Repository visitors miss desktop downloads and current features. Unqualified clone commands get old source. Dependency PRs target the older baseline. | Review and bring the intended release baseline into `main`, then verify the public landing page and every quick-start command. |
| Before promotion | Installation favors source work | The desktop README starts with uv. Server installation requires two Git checkouts, ownership changes, and manual image loading or building. | Put native downloads first. Make a prebuilt Compose deployment the default server path. |
| Before the next release | Publication does not gather desktop artifacts | The server/Python release can publish without the five native downloads described in its notes. | Build and validate every artifact from one tag, gather them into a draft, and publish only when the required set is complete. |
| Before recommending easy server setup | Container CI stops at imports | A green build does not prove the documented Compose setup, HTTP readiness, saving, and restart work together. | Run the supported installation path in an isolated test project with disposable storage and verify lifecycle behavior. |
| Before broad desktop promotion | Windows and Mac bundles are unsigned | A successful build can still be difficult to open on a stranger's computer. | Add publisher signing and Mac notarization when feasible. Until then, show the unsigned status before download and test first launch on fresh machines. |
| Next | Operational claims lack measurements | Users cannot confidently choose hardware or estimate disk growth for an always-on adventure. | Publish measured CPU, RAM, storage, and 24 to 48 hour observations on representative x86-64 and ARM64 machines. |

### Public branch and landing page

The public `main` README currently points to rc6 and has no desktop installation
section. Even the newer README uses an unqualified `git clone`, which selects that
older default branch. Resolve branch alignment before sending repository links to
a broad audience. Until it is resolved, use the explicit rc31 release URL.

After alignment, put two choices immediately below the opening screenshot:

- **Download for my computer:** explicit Windows, Apple Silicon Mac, Intel Mac,
  Linux x86-64, and Linux ARM64 links, followed by extract, open, and choose ROM.
- **Run on my home server:** a short prebuilt Compose guide with prerequisites,
  storage location, access instructions, and a link to updates and backups.

Move developer installation beneath those paths. Keep the ROM requirement, beta
status, and requirement to keep the host awake visible. Use a plain-language download
label even if the asset filename retains architecture names such as `aarch64`.
Document tested minimum operating-system versions, not just CPU architectures.

### Server packaging

Publish versioned container images to a public GHCR package for `linux/amd64` and
`linux/arm64`, after native validation of both targets. Use explicit version tags
and record digests. A public package supports anonymous pulls, but package visibility
must be configured and verified independently of repository visibility.
See [GitHub Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

Keep the downloadable image archive as an offline option. The normal installation
should need only the release Compose file, a small configuration file, Docker, and
the user's ROM. It should not require a PokeSim source checkout or a reference Git
checkout. An architecture-aware manifest lets Docker select the appropriate image.
See [Docker multi-platform builds](https://docs.docker.com/build/building/multi-platform/).

Reuse the verified archive preparation in `pokesim/desktop_setup.py` through a
shared preparation module and supported server command. Support an explicit offline
archive too. Make first setup retryable and preserve saves on every retry. Prefer a
setup service that completes successfully before the main service starts, with
clear download and filesystem errors. The existing `prepare-data` service disables
networking, so archive downloading needs an intentional change to that setup path.

Offer a named-volume default to avoid a manual `sudo chown` step, while retaining
a documented bind-mount option for experienced home-server users. Validate initial
ownership with the actual unprivileged image and provide matching backup and restore
commands. Do not silently migrate existing bind-mounted data.

The current localhost bind is useful, but a remote server's localhost is not the
visitor's laptop. Include a simple SSH-tunnel example for an initial remote-server
visit, and retain the authenticated HTTPS recipe for persistent remote access.
Do not turn the loopback-only desktop launcher into a public setup service by merely
changing its bind address. Its origin checks and shutdown token assume local use.

### Release orchestration

The original [`release.yml`](https://github.com/afk-sapien/PokeSim/blob/6570c41/.github/workflows/release.yml) builds Python packages and one
container image, then publishes immediately. It does not invoke or download outputs
from [`desktop.yml`](https://github.com/afk-sapien/PokeSim/blob/6570c41/.github/workflows/desktop.yml). That workflow uploads CI
artifacts only. The existing rc31 desktop assets are present, but their attachment
is not reproduced by the checked-in publication workflow.

Use a release workflow with reusable native-build and container-build jobs. Every
job must check out the requested tag and report the same resolved commit. Gather
the outputs only after validation succeeds. Verify all expected filenames, versions,
platforms, and source identities before publishing the draft release.

Generate one manifest and checksum set covering desktop, container, Python, and
configuration downloads. The present primary `SHA256SUMS` is generated before
desktop assets are gathered. Desktop downloads have separate checksums. A unified
manifest makes completeness checks and support easier. Preserve separate checksum
files too if convenient for individual downloads.

Keep release artifacts immutable after publication. Make interrupted draft assembly
retryable without replacing an already published version. Specify prerelease status
deliberately. The current publisher always passes `--prerelease`, including for a
version without an `rc` suffix.

### CI and package validation

The original [`ci.yml`](https://github.com/afk-sapien/PokeSim/blob/6570c41/.github/workflows/ci.yml) validates Compose syntax, builds the image,
prepares reference data in a named volume, and checks runtime imports and non-root
identity. It does not launch the documented hardened Compose service or poll its
health endpoint. Add a bounded smoke scenario that checks startup, an HTTP response,
clean shutdown, persistent storage, and restart using the artifact intended for release.

Use synthetic fixtures or PyBoy's demonstration ROM for public CI where appropriate.
They cannot establish Pokémon-specific gameplay or checkpoint compatibility. Keep
those checks in private release validation with user-supplied inputs.

Add an installed-wheel check outside the source directory, including launcher entry
points and packaged static files. The current archive checker is useful, but source
tests can hide missing installed resources. Require both wheel and source archive
to exist. Currently `tools/check_package.py` accepts either one on its own.

Smoke-test desktop archives after extraction as well as their build directories.
This checks the actual downloadable packaging and permission preservation. Retain
native diagnostics on failure, and set explicit job timeouts.

The GitHub rulesets endpoint returned no rulesets and `main` was reported unprotected.
After branch alignment, require the intended CI checks for merges and protect release
tags. Make deliberate exceptions for maintainer recovery rather than depending on
habit. Do not treat a green dependency PR against rc6 as validation against rc31.

Add CI concurrency cancellation for superseded branch runs. Consider a smaller fast
PR matrix with full native packaging on relevant changes, scheduled checks, and
every release. Keep the complete release matrix mandatory. Add vulnerability scanning
with a documented triage process and artifact provenance after the installation and
publication gaps are fixed.

## Proposed implementation sequence

| Change | Scope | Acceptance check |
| --- | --- | --- |
| 1. Align the public release baseline | Review the development branch, update `main`, lead with downloads, correct source commands | An anonymous visitor reaches rc31 downloads and a new clone matches the documented source |
| 2. Simplify server setup | Public images, native ARM64 validation, verified archive preparation, easy persistence, focused server quick start | A clean machine installs without Git, Python, local builds, registry login, or manual ownership changes on the default path |
| 3. Unify publication | Reusable build jobs, draft assembly, complete manifest, version checks | One requested tag produces all supported artifacts, and any missing target prevents publication |
| 4. Test customer installation | Extracted desktop smoke, installed wheel smoke, Compose lifecycle, upgrade and restore rehearsal | Downloaded artifacts start and resume with preserved data on each supported target |
| 5. Reduce support friction | Signing, tested OS and hardware table, support diagnostics, measured endurance | Testers can identify their download, open it, locate saves, and submit a useful issue without sharing private files |

Signing can run alongside the server and CI work because it involves external
publisher credentials. PyPI, Homebrew, WinGet, Unraid, and other catalogs can follow
once the main desktop and Docker paths are reliable. They add maintenance surfaces
and should not delay these core fixes.

For a small Reddit beta, ask fresh-machine testers to follow only the public guide
and record the first point of confusion. Before a broader announcement, require
successful first install, shutdown and resume, upgrade with backup, and restore on
the supported distribution paths. Describe autonomous gameplay as experimental until
the longer reliability evidence supports a stronger claim.

## Checks performed during this review and implementation

- Read public branch metadata, release assets, workflow outcomes, open dependency
  PRs, rulesets, and branch protection indicators through the GitHub API.
- Documentation link checker passed for all 31 Markdown files after the changes.
- JavaScript checks passed for eight scripts and four Node test files.
- `docker compose config --quiet` passed.
- Built source archives and wheels from this working tree, then passed the
  runtime-resource and excluded-file checker. A fresh installed wheel passed the
  launcher smoke outside the source tree with dependencies resolved from metadata.
- The final ROM-free suite passed 624 tests with 11 skips and one dependency
  deprecation warning, including the new preparation and release-assembly scenarios.
- Built the container and passed the isolated Compose setup, HTTP readiness,
  checkpoint hash, clean shutdown, and restored-startup checks.
- All three updated workflows passed actionlint.
- Rebuilt the Linux x86-64 desktop archive in an isolated locked environment, then
  passed launcher and bundled-runtime checks against its extracted contents.

The initial sandboxed HTTP tests stalled. The bounded rerun outside the sandbox
passed. Packaging required downloading the declared build dependency after the
offline attempt could not resolve it. These were environment limitations, not
observed packaging defects.

This was not a new Windows, macOS, or ARM64 installation qualification, security
audit, or multi-day gameplay test. The local packages include the existing dashboard
edits and are audit artifacts, not release candidates. Existing native CI successes
and the rc31 receipt are historical evidence. Upload verification is implemented
but has not been exercised by publishing a release in this pass.
