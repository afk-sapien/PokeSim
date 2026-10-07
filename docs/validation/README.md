# Validation evidence

Keep records that support the current release, unresolved investigations, or
technical decisions that still affect the project. These are dated observations,
not live status or substitutes for executable regression tests.

## Retained records

- [0.4.20 publication receipt](release-0.4.20.json): PP menu hotfix, source
  revision, image digest, public download checks, and cross-platform validation.

- [0.4.19 publication receipt](release-0.4.19.json): bag and Transform fixes, source
  revision, public download checks, and cross-platform validation.

- [0.4.18 publication receipt](release-0.4.18.json): combined release, source revision,
  image digest, public download checks, and cross-platform validation.

- [0.4.17 publication receipt](release-0.4.17.json): source revision, image digest,
  publication checks, and supported installation results.
- [0.4.17 candidate review](release-candidate-0417-20261003.md): detailed checks
  and limitations behind the release. Earlier pending-publication statements
  describe the candidate at that time. See [release status](../../RELEASE_STATUS.md).
- [Withdrawal recovery and unresolved DV mutation](withdrawal-hp-recovery-20261003.md):
  reproduced failure, recovery, and the remaining investigation.
- [Generated game data review](game-data-content-review-20261002.md) and
  [measurements](game-data-content-review-20261002.json): distribution-boundary
  analysis and the data supporting it.
- [Security hardening review](security-hardening-20260919.md): request boundaries,
  deployment assumptions, and outstanding findings at the time of the review.
  Advisory counts describe that snapshot, not the current security status.

## Older records

The [complete archive before cleanup](https://github.com/afk-sapien/PokeSim/tree/5ea6630aab466cbf1f02abde4e3912ee3e90f0b6/docs/validation)
contains the former monitoring snapshots, release receipts, experiment reports,
and saved patches. Existing historical citations link to individual files at
that same immutable revision, `5ea6630aab466cbf1f02abde4e3912ee3e90f0b6`.

The cleanup removes those files from the current tree without rewriting Git
history. To inspect one locally, use `git show REVISION:docs/validation/FILENAME`
with the revision above and its original filename. The commit must be available
locally, which may require fetching older history in a shallow clone.

## Adding evidence

Keep routine run output and private observations outside Git. Put reproducible
checks in `tests/` or `tools/`, summarize relevant results in the pull request,
and retain a sanitized report here when it supports a release, an unresolved
problem, or a lasting technical decision. Include the revision, inputs, duration,
and limitations. Never include ROMs, saves, private checkpoints, or tokens.

Review retained evidence when its release is superseded or its investigation
closes. Preserve useful conclusions in the owning guide and link to Git history
for the original record instead of maintaining duplicate reports.
