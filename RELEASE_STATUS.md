# Release preparation: 0.4.5

This release simplifies desktop and Docker installation. User-account installers handle
Python 3.12 and the released wheel. New Docker libraries can use a named volume without
manual ownership preparation. Existing bind-mount libraries keep their data paths.

The setup review fixes isolate Docker smoke tests from inherited Compose settings, preserve
the named volume when enabling the HTTPS proxy, and serve public install commands from
completed releases instead of the development branch. Publication verifies a draft's downloads
before making it the latest release. An autosave ordering fix resolves equal filesystem timestamps deterministically.
No save-format or schema change is introduced.

## Validation

Local verification passed 1,349 Python tests with 69 skipped, plus JavaScript checks,
lint, package validation, an installed-wheel launcher and repeat-installation smoke test,
and the Docker named-volume lifecycle check. Focused regression tests cover configuration
isolation and proxy storage preservation.

Release workflow validation covers installer retries, configuration isolation,
proxy volume preservation, package resources, and Docker startup and persistence. The release
workflow also gates publication on the full Python and browser suites, native installation
on Windows x86-64, Intel macOS, Apple Silicon, Linux x86-64 and ARM64, and container lifecycle
checks. Test results and the deployed version are recorded after those checks complete.

See [release notes](docs/release-notes.md), [desktop installation](docs/desktop.md), and
[self-hosting](docs/self-hosting.md).

## Known limits, deliberately not addressed here

- **Recovery never gives up.** An exchange that cannot be finished is retried forever, now slowly.
  A ceiling would mean abandoning an exchange already committed on one side, which is the one
  path that can actually lose a Pokémon. It needs a design and a test, not a constant. Until
  then, a permanently stuck exchange still freezes stop, archive, edit and backup for that pair,
  and the only exit is to resolve whatever the recovery is failing on.
- **The commit path still holds `self.guard` across the two stage calls**, up to 55 seconds each,
  so a cancel that arrives during staging waits for them. That ordering is deliberate: a cancel
  must not race a commit.
- **The scheduler's candidate search is still quadratic** in offers, and re-runs from scratch every
  ten seconds, though each combination is now cheap: about 0.2 s per pair of full libraries.
- **The bundled broker Compose file serves an unauthenticated endpoint on 0.0.0.0** and returns
  full inventories, and that endpoint is expensive to compute. The broker is optional and is not
  part of the Library deployment; do not expose it beyond a trusted network.
- **Journal screenshots already stored blank are not repaired**, including the one in the shipped
  Journal image. Only new entries are retaken.
- **Seen counts, level 100 species and perfect finds have no backfill.** Journal entries never
  recorded them, so their history starts with 0.4.0 (seen) and 0.4.2 (the other two).
- **Hall of Fame teams still do not rotate.** A rematch fights with whichever six remain in the
  party. Choosing a varied team is a gameplay change that needs its own endurance run.
- **Legacy per-entry rewind states are kept** (about 24 MB for the busiest adventure). They stopped
  growing in an earlier release and are what lets an old Journal entry rewind.
- **No formatter or type checker.** Ruff runs the Pyflakes rules only, and 15% of functions carry
  return annotations.

Gameplay remains an experimental beta. Synthetic tests, a single mature-save replay and
demonstration-ROM worker checks do not establish uninterrupted multi-day cartridge gameplay on
all platforms. Existing private gameplay and cable-trading receipts retain their original scope.
Back up the complete library before upgrading. Import legacy adventures into a new application
folder with the old application stopped.

[Historical release and deployment records](docs/history/releases-through-rc31.md) remain
available for earlier version receipts and their limitations.
