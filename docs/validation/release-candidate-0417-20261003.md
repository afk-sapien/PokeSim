# PokeSim 0.4.17 combined candidate review

Reviewed and validated on October 3, 2026. This is the complete local candidate
against the 0.4.16 checkout, including new files. It is not a published release.

## Code review

Reviewed the combined changes in notification delivery and migration, backup
loading and deletion, nickname validation, intro naming, audio and checkpoint
handling, gameplay recovery, managed routes, live controls, responsive layouts,
and packaging. The review did not identify an additional release-blocking defect.
This is a manual review with regression evidence, not a claim of exhaustive proof.

- Notification migration preserves existing credentials, filters and subscriptions.
  Named integrations isolate provider credentials and route events independently.
  Regression coverage includes concurrent edits, retries, provider failures and
  suppressing credential-bearing HTTP logs. This sweep used simulated providers.
  The owner previously confirmed live Discord delivery. No live messages were sent
  during this review and deployment.
- Backup copies are checksummed before loading and start stopped with automatic
  trading disabled. Deletion validates the identifier and requires the same CSRF
  session as other writes. Tests cover cancellation, failed deletion, retry,
  pagination and preserving current adventures and previously restored copies.
- Audio is opt-in at every speed. Buffers are bounded and browser playback stops
  on navigation. Tests cover mute, paused playback, retries and multiple speeds.
  Cartridge checks cover existing checkpoint compatibility. Physical speaker
  quality and every browser/device combination are not established by these tests.
- Naming validates the game's limits, preserves older settings and rejects an
  empty nickname pool. Trainer and rival choices apply at adventure creation.
- Recovery retains strict save validation. The excess-HP grace is limited to a
  Pokémon Center and to snapshots with no other invalid fields. The original
  historical DV-byte mutation remains unexplained. See the separate
  [recovery investigation](withdrawal-hp-recovery-20261003.md).
- Release documentation was stale and omitted backup deletion. The release notes,
  operations guide and release status now reflect the combined candidate.

## Validation results

| Check | Result |
| --- | --- |
| Full non-browser regression suite on Python 3.12 | 1,639 passed, 50 skipped |
| Separate cartridge suite | 5 passed |
| Complete Chromium browser suite | 98 passed |
| Browser-script checks | 82 passed |
| Repository Ruff checks | Passed |
| Markdown link destinations | Passed |
| Wheel and source archive resource checks | Passed |
| Fresh Linux Python installation outside checkout | Passed |
| Linux installer, launch and repeat installation | Passed |
| Docker legacy setup, offline retry, health, save and resume | Passed |
| Docker Library startup, session, shutdown and restart | Passed |
| Fresh Docker quick start and persistent named volume | Passed |
| Authenticated HTTPS proxy and private-route checks | Passed |
| Built-image source comparison | All 155 Python and UI files match |

The 50 skips are not passes. This sweep does not replace the Windows, macOS and
Python-version release matrix. Those CI gates must run before public publication.
Long-running cartridge behavior and the existing trading-recovery limitations
remain as documented in RELEASE_STATUS.md.

## Candidate artifact

- Image: `pokesim-local:0.4.17-candidate-20261003`
- Image ID: `sha256:054d309247998c6a9c393bae847eef2bbc2a41996829ca81d5c76e2fe284057f`
- Revision label: `local-0.4.17-candidate-20261003`
- Core: 0.1.4, unchanged

All application and UI sources in the image were compared by SHA-256 with the
working tree. The source manifest is retained locally at
`/tmp/pokesim-0417-source-manifest.json`. Validation command logs are retained under
`/tmp/pokesim-0417-*.log`. Documentation-only receipt updates after the image build
do not change its application code.

Public publishing is on hold. No Git push, public tag, GitHub release or registry
publication was performed for this candidate.

## Home-server deployment and visual verification

The owner authorized the complete candidate deployment before public release.
Deployment completed successfully on October 3. The home server selects the
candidate image persistently through its existing Compose environment file.
The previous image remains available for rollback.

- Verified cold backup: `/docker/pokesim-app/backups/pre-0.4.17-20261003T174532Z.tar.gz`
- Backup size: 610,123,268 bytes, with 68,885 archive entries
- Backup SHA-256: `b1f9219fa9ce442a206579fceab22c9b66640a0890d16b03982309a5fa1161c7`
- Deployment receipt: `/docker/pokesim-app/backups/candidate-0.4.17-20261003T174532Z.json`
- Previous environment: `/docker/pokesim-app/.env.bak-20261003T174532Z-pre-0.4.17`

After deployment, Red, Blue, Fresh Start and Release Check all reported 0.4.17,
healthy workers and advancing frames. Each reported zero reloads since restart.
Bababa remained stopped. The container passed its health check and its startup
log had no errors. These are immediate post-deployment observations, not a
long-running endurance guarantee.

Actual home-server Notifications, Settings and Live pages were captured and
visually inspected at 1280px and 320px. The new integration panel, nickname editor
entry point, backup actions, live speed control, sound toggle and portrait
backgrounds are present. There was no horizontal page overflow or JavaScript
page error. Existing server ntfy configuration remains present. Local-preview
Discord and Telegram credentials were not copied to the home server.

Private verification screenshots and frame observations are retained in
`/tmp/pokesim-0417-server-ui/`. No real notification test, backup deletion or
backup restoration was performed on the home server during this verification.

## Live speed label follow-up

The owner requested removing the visible Speed label from the live controls.
The selector retains its accessible name and tooltip. Ten existing live layout
and speed-control browser tests passed. The complete candidate was rebuilt as
`pokesim-local:0.4.17-candidate-20261003-ui1`, image ID
`sha256:2c7725dc2f06245429cbe8e602e6ec32f5fe7999fbb2d77e0733fbe3950a13cd`.
It supersedes the initial candidate on the home server.

The verified backup and deployment receipt use timestamp `20261003T175545Z`
under `/docker/pokesim-app/backups/`. The service is healthy and all four running
adventures resumed. The actual desktop and mobile controls were visually checked
on the server after deployment. Public publication remains on hold.

## Return visits and gifts follow-up

Adventure Stats now presents repeat-event and Mew requirements as responsive
cards with state badges, walking progress and a ready count. A zero-step event
that has not reopened is labelled Pending rather than Ready. First Mew gifts
and repeat gifts distinguish the Champion or subsequent League requirement.
The status APIs expose the configured event and Mew intervals for the meters.

The focused statistics and repeat-event suite passed 52 tests. All 10 statistics
browser tests passed, including phone, tablet and desktop cards, both themes,
walking, pending, ready, first gift, League requirement and disabled states.
Browser scripts, Ruff and documentation links passed.

The full image `pokesim-local:0.4.17-candidate-20261003-ui2` supersedes ui1 on the
home server. Its image ID is
`sha256:d3b236f437018807205e5d67a294f85f3ea8cb5160a9eaa337536734f8de3db8`.
The cold backup and deployment receipt use timestamp `20261003T180310Z` under
`/docker/pokesim-app/backups/`. The container is healthy, all four previously
running adventures resumed and Bababa stayed stopped. Actual server stats cards
were visually inspected at 1280px and 320px. Public publication remains on hold.

## Home-server cartridge portrait migration

The owner requested replacing the server's existing colored sprite pack. The
extractor intentionally preserves existing packs, which explained why upgrading
the application alone had left that pack in use.

On October 3, the installed Red and Blue ROMs were verified on the server and
used to generate 151 native-size portraits for each of five adventures. The
shared fallback was also replaced. Every generated PNG was checked against the
extractor's four-shade palette before installation. No ROM left the server and
no artwork download was used. This changes the source of displayed portraits,
not any conclusion about rights to the underlying game artwork.

The old pack and migration receipt remain private at
`/data/assets/portrait-backups/20261003T180917Z` in the server data mount.
Live, PC and Pokédex pages were visually inspected and served images were
verified against the cartridge palette. All five adventures serve extracted
portraits. The games were not restarted. The decoder suite passed five tests
with one reference-dependent check skipped. This initially left old one-day browser
cache entries usable. The follow-up below corrects that omission.


## Portrait cache follow-up

The earlier migration replaced image files at unchanged URLs. Browsers were
allowed to reuse those URLs for 24 hours, so a fresh-browser check missed the
old artwork that existing viewers could still see. All portrait consumers now
use a new query version, including Live, PC, Pokédex, trading and Library trade
cards. Both standalone and managed image routes require cache revalidation on
later requests. The new URLs bypass already-fresh entries from the legacy pack.

The targeted route and browser suite passed 34 tests. Its new Chromium regression
first proves that the legacy colored image remains cached after the backing file
changes, then verifies that the actual Pokédex displays the replacement. A later
file replacement also appears in the PC without a cache clear. All 48 coordinator
checks and all 10 browser-script test files passed. Scoped image addresses and
custom portrait overrides remain supported.

The home server now runs `pokesim-local:0.4.17-candidate-20261003-ui3`, image
`sha256:c6acf2472d434382a10dbf5a98d809a08d24b1a6ae89d087ede274d8c2545841`.
The verified cold backup and deployment receipt are timestamped
`20261003T182246Z` under `/docker/pokesim-app/backups/`. The service is healthy,
all four running adventures resumed and Bababa remains stopped. On the public
server, the actual rendered Live, PC and Pokédex images passed pixel-palette,
versioned-URL and cache-header checks. The Pokédex screenshot was visually
inspected. A normal navigation or reload is sufficient to pick up the new URLs.
Public publication remains on hold.

After the owner reported mixed portraits, a complete follow-up audit compared all
755 adventure PNGs against fresh extraction from each adventure's installed ROM.
Every byte sequence matched. All 151 Red portrait URLs fetched through the public
HTTPS origin matched those server hashes and returned `private, no-cache`.
A real Chromium page loaded all 151 images, including those normally lazy-loaded,
and checked their rendered pixels. Every image used the new URL and cartridge
palette. The displayed grid was visually inspected. This audit did not reproduce
the owner's mixed set in the existing browser tab, so a specific affected species
was requested and a fresh document URL was opened for comparison. No additional
server mutation or deployment was made based on an unconfirmed cause.

## Optional community sprite installer

Settings now offers an explicit download of the 151 colored Red/Blue PNGs from
PokéAPI revision `bfb75391935310368065096fa08c51e8970bc43e`. Visiting Settings,
starting PokeSim and adding a ROM do not trigger it. The application downloads
only after the install action, preserves the upstream notice and stores the pack
in user data. No pack is bundled or mirrored by PokeSim.

Four bounded download workers fetch fixed HTTPS paths without redirects. Each
image is size limited and decoded for validation. A staged directory becomes
available only after all 151 images succeed. Activation is persisted separately
from original portraits. Failures remove staging, preserve current artwork and
allow retry. The owner can restore defaults or reuse an installed pack offline.
All managed portrait consumers use the same override and revalidation policy.

Validation passed 32 installer, route and delivery tests, 13 Settings browser
checks covering artwork, backups and nicknames, the cached-portrait browser
regression, and all 82 browser-script checks. Ruff and documentation links passed.
An actual upstream installation fetched all 151 images and the source notice.
The downloaded Pikachu matched the server's backed-up original colored sprite.
Actual downloaded previews were visually inspected at 1280px and 320px, and
restore and re-enable actions were exercised in Chromium. Synthetic failure tests
cover HTTP errors, redirects, oversized files, invalid PNGs, retry, duplicate
starts and shutdown cancellation. Request tests enforce CSRF on both mutations.

The home server now runs `pokesim-local:0.4.17-candidate-20261003-ui4`, image
`sha256:c51a0aad70a107cb9e779823a37e8bed9311a98f601adcecb3df08e7e20cfd33`.
The complete cold backup and deployment receipt use timestamp `20261003T190139Z`
under `/docker/pokesim-app/backups/`. The deployed Settings panel was visually
inspected at desktop and phone widths. Its API confirms the pack is uninstalled
and defaults remain active. All four previously running adventures resumed.
The local preview backend was also restarted and its adventure is running.
The installed container was checked for the new module and UI and for absence of
bundled sprite-pack PNGs. Public publication remains on hold.

## Final follow-up review

A second review examined interactions among sprite installation, backup snapshots,
notification updates, audio checkpoints, and the combined application routes.
It found one additional defect in the candidate, fixed before publication.

### Fixed: backup overlaps with sprite installation

Backup staging recursively copied the temporary `.install-*` directories under
assets. A sprite installer could rename its staging directory into place during
that copy, causing `shutil.copytree` to fail. A slower download could instead leave
unfinished download files inside the archive. Backups now exclude those temporary
directories and retain completed portrait packs.

The new regression simulates a download activating just as backup copying begins.
It failed with `shutil.Error` against the original implementation in an isolated
process. It passes with the fix, verifies the ZIP has no download staging entries,
and successfully restores the resulting backup database.

### Fresh validation

- Complete non-browser suite: 1,648 passed, 50 skipped, before the small backup fix.
- Complete browser suite: 104 passed.
- After the fix: 29 focused tests passed across portraits, backup loading,
  backup concurrency, backup compression and all five cartridge tests.
- Ruff and whitespace checks passed. Local links in 84 Markdown files passed.
- Browser script syntax and Node checks passed, covering 16 scripts, 10 test files
  and 82 individual Node tests.
- The skip conditions and native Windows, macOS and Python-matrix limits above
  still apply. The existing Starlette/AnyIO deprecation warning is unchanged.

### Home-server visual review

Reviewed the deployed Library, Settings, Notifications, Live, PC, Pokédex,
Journal, Adventure Stats and adventure Trading pages at widths of 1,280, 780
and 390 pixels. All 27 page checks returned HTTP 200 with no JavaScript page
errors, broken loaded images or horizontal document overflow. Inspected actual
screenshots, including the narrower two-column PC layout, artwork previews,
backup actions, journal navigation, return-visit cards and live controls.

Also opened the notification editor, nickname editor, new-adventure form,
PC detail panel and fullscreen game view at desktop and phone widths. No forms
were submitted and no real notification tests were sent. Screenshots and the
read-only browser results are stored locally under
`/tmp/pokesim-final-ui-review/`.

The owner has enabled the community artwork pack on the server. The review
confirmed its previews and the adventure portraits display the selected pack.
This pass found no additional layout defect. Physical audio quality and long-term
unattended gameplay remain outside this short review's scope.

### Follow-up deployment

The complete candidate, including the backup fix, is deployed as
`pokesim-local:0.4.17-candidate-20261003-ui5`, image
`sha256:43fdfc6ec5c9c4e64ce2826e0083bece3cb3bc604df94f8a34aa47e3b436999d`.
The verified cold backup is
`/docker/pokesim-app/backups/pre-0.4.17-20261003T194411Z.tar.gz`, with SHA-256
`afc25800f5ea46282cfbd03f22f075a6949ff4d76eddcb05404e11a5073f407b`.
The deployment receipt has the same timestamp in the backups directory.

Post-restart checks confirmed the installed backup exclusion, a healthy service,
four resumed adventures, and the archived adventure still stopped. Adventure
settings and the active community artwork selection were preserved. No public
release, tag, package upload or Git push was performed.

## Fresh Docker installation with a real cartridge

A further acceptance test used the exact reviewed `ui5` image and the repository's
unmodified `compose.quickstart.yaml` in a new temporary installation directory.
The image tag and a free loopback port were supplied through `.env`. Docker created
a brand-new named volume. No reference data, application database, saves, sprites
or notification credentials were preloaded. This was a local image test, not a
pull of a published 0.4.17 image.

- Compose became healthy with the documented non-root UID 10001, read-only root
  filesystem, dropped capabilities and 256 MiB temporary filesystem.
- The empty Library rendered correctly and had no ROMs or adventures.
- Uploaded the existing local supported Red cartridge through the browser.
  Automatic game-data preparation and worker startup completed in 4.07 seconds.
  The original missing-game-data error did not occur. No manual prepare command
  was needed.
- Generated names appeared in the creation form. Custom names FRESH and RIVAL
  were entered correctly inside the game. The selected Bulbasaur was acquired.
  The run reached seven registered species without a recovery reload or invalid
  game state.
- Live Max and 4x speed selection, sound streaming, pause/resume, checkpoint save,
  and export of a verified 32 KiB SRAM save passed. Audio quality was not assessed
  through physical speakers.
- All 151 default portraits were extracted from the cartridge at native sizes.
  Community artwork remained absent until explicitly installed. A real upstream
  download, restoring cartridge artwork, and re-enabling the cached pack passed.
- Added a custom full nickname. Created a backup, restored an isolated stopped
  adventure, and deleted the test backup through the Settings UI. The restored
  copy retained its automatic-trading block.
- Stopped and removed the original container, retained its named volume, and
  created a new container with Compose. The original adventure resumed at frame
  1,109,390 after the pre-stop observation at frame 1,108,426, then advanced further.
  Names, collection, 4x speed, nickname customization and selected artwork survived.
  The restored copy remained stopped. Health was good and recovery reloads were zero.

This covers first installation and early gameplay on Linux x86-64 Docker with
Python 3.14. It does not establish a complete new-game League playthrough or
native Windows/macOS behavior. The home-server installation was not changed by
this fresh-install test. Local test receipts and screenshots are under
`/tmp/pokesim-fresh-ec50369c0c-zy6y7dt5`.

After recreation, phone-width Library, PC, Pokédex and Adventure Stats checks
passed without horizontal overflow or browser errors. The nickname editor still
contained the saved custom name. The disposable test container, network and
volume were removed after verification. Test receipts, screenshots and the private
exported save remain local in the temporary test directory.
