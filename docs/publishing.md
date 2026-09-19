# Publishing a release

The release workflow publishes Python packages, a Linux amd64 image at
`ghcr.io/afk-sapien/pokesim:<version>`, and versioned Compose downloads.
Standalone executables and app bundles are excluded. The image archive remains
available as a checksummed release download for offline loading.

## Trigger and checks

Ordinary branch pushes and pull requests do not publish anything. When ready to
release, update `pyproject.toml`, the lockfile, Docker defaults, and release notes
for the chosen version. Commit and merge the reviewed changes to `main`. Then create
and publish a GitHub release for a new `v<version>` tag on that commit, using
`docs/release-notes.md` as its description:

```sh
gh release create v0.1.0 --target main --title "PokeSim 0.1.0" --notes-file docs/release-notes.md
```

Publishing the release automatically starts the **Publish public release**
workflow, which attaches the downloads. A bare tag push does not publish anything.
The tag must match the package version and release notes heading.

To retry a failed run, start that workflow manually with the release's tag. It
refuses a version whose downloads are already attached.

The workflow validates Python installation on all configured targets, runs Python
and browser tests, builds the wheel and source package, and builds and tests the
Linux amd64 image. Only then does it log in to GHCR with the repository's temporary
`GITHUB_TOKEN` and push the exact version tag. No personal access token or added
repository secret is needed. The publishing job has `packages: write` and
`contents: write`, while other jobs retain read-only repository access.

It next pulls the image using an empty Docker credentials directory and verifies
that it has the same image ID as the tested build. Release assembly records the
registry digest, image ID, source revision, platform, and file checksums. Both
`compose.yaml` and `env.example` select the exact version. The workflow uploads the
downloads to the release and verifies every uploaded checksum. Versions containing
`rc` are marked as prereleases. No floating `latest` tag is published.

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

A failed check before image publication leaves GHCR unchanged, but the GitHub
release stays visible without downloads. Once the image has been pushed, a later
failure can leave that image in GHCR with an incomplete asset list. Inspect the
failure and rerun the workflow manually against the same unchanged tag. It replaces
partial assets and checks the complete asset set. Never move a published tag. Fix
released software in a new version.

Rerunning an unpublished candidate can rebuild and replace its registry tag.
The final manifest records the verified digest for that run. Published releases
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
