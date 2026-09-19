Security hardening validation, September 19, 2026

This pass reviewed the Adventure Library manager, private worker proxy, browser request boundaries, legacy launcher, archive imports and restores, container defaults, and authenticated proxy deployment.

Changes:

- Replaced the worker proxy's path blacklist with an explicit public-route allowlist. An encoded single-dot path previously passed the blacklist and was normalized by HTTPX into a private worker route. Regression tests cover encoded dots, separators, query delimiters, fragments, and private endpoints across GET, POST, and HEAD.
- Added content security and same-origin resource policies. Real Chromium tests verify that the library's scripts and settings still work while injected inline scripts are blocked.
- Added Host, Origin, and Fetch Metadata checks to the legacy launcher, with matching health-probe behavior. The manager now rejects invalid public origins before opening its data directory.
- Rejected archive paths containing Windows device names, ambiguous components, control characters, or existing symbolic links. Backup member checksums now stream from disk instead of loading a whole member into memory.
- Restricted the Caddy container to a read-only root filesystem, no new privileges, and its required port-binding capability. Corrected the proxy's library data-directory example and documented the distinction between viewer-only controls and library administration.
- Added locked runtime dependency auditing and an actual authenticated TLS deployment check to CI.
- Moved the application image from Debian 12 to Debian 13, applied available OS updates, and removed unused desktop graphics libraries. Debian records the older SQLite issue as fixed in the newer distribution. See the [Debian SQLite advisory](https://security-tracker.debian.org/tracker/CVE-2025-7458).
- Added a reproducible proxy build using Caddy 2.11.4, Go 1.27.1, and locked patched Go modules. It includes dependency license notices and the compiled package list. Dependabot covers its Docker and Go dependencies. CI scans both images and rejects fixable high and critical advisories.

Local validation:

- Full working-tree Python suite with Chromium enabled: 1,213 passed, 31 optional checks skipped. The working tree also contained separately prepared publishing changes, which this security change preserves without committing.
- Focused security and affected-route suite: 123 passed.
- Browser JavaScript checks, documentation links, workflow linting, and patch whitespace checks passed.
- A local application image built successfully. Disposable legacy and library Compose deployments passed startup, health checks, saves, shutdown, and restart.
- The disposable Caddy deployment passed certificate and hostname verification, missing and invalid authentication on every tested route, CSRF checks, cross-origin rejection, private-route rejection, and inspection confirming no published backend port. Test containers and volumes were removed afterward.
- pip-audit 2.10.1 found no known advisories in 27 locked runtime packages selected for the audit environment. A separate installed-environment scan covered 35 third-party packages with no advisories. The editable application itself was excluded from that package advisory lookup.
- Gitleaks 8.30.1 scanned 117 commits reachable through local refs. Its 11 findings were reviewed and identified as game trade fingerprints, the `pokedex-milestones-v1` storage key, and Pokémon Secret Key objective text. No credential was identified by that scan.

Limits:

The initial Trivy 0.74.0 application-image scan reported 430 package/advisory pairs, including 16 critical findings and eight findings with available fixes. The updated Debian 13 image has no critical findings and no findings with an available distribution fix. It still reports 223 package/advisory pairs across 110 distinct advisories: 54 high, 72 medium, 96 low, and one unknown. These are retained as outstanding upstream findings, not suppressed or reported as a clean OS scan.

The remaining high findings concern util-linux mount and namespace tools, ACL handling, libcurl connection handling, Expat XML parsing, ncurses, Perl Archive::Tar, and systemd-homed. The supplied application runs without privileges or mount capabilities, does not run systemd-homed, uses Python HTTP and ZIP implementations, and does not offer arbitrary SQL, XML parsing, Perl archive extraction, or terminal tools over its HTTP interface. These constraints reduce exposure. They are not proof that every installed library is unreachable or safe. Keep tracking upstream updates.

The proxy retains CEL 0.28.1 because Caddy 2.11.4 does not compile against CEL 0.29.0's changed interpreter API. The [medium-severity CEL advisory](https://github.com/advisories/GHSA-gcjh-h69q-9w9g) concerns user-supplied expressions and native Go structs exposed through JSON tag parsing. The supplied Caddyfile contains no CEL expressions and exposes no expression-submission API. This advisory is documented and not suppressed. Reassess it before adding custom expression matchers or replacing the supplied proxy configuration.

The final rebuilt proxy scan reports no OS findings, no high or critical findings, one medium CEL finding, and one unknown-severity module warning. The latter is [Go's warning about the unmaintained OpenPGP package](https://pkg.go.dev/vuln/GO-2026-5932). The compiled package list confirms that `golang.org/x/crypto/openpgp` is not included in this proxy binary. The authenticated TLS regression test passed against this rebuilt image. The matching application image passed both legacy and library save/restart checks after the Debian upgrade and graphics-library removal.

This is a targeted engineering review, not an independent penetration test or a guarantee of zero vulnerabilities. Package advisory results are a point-in-time check, not a full audit of native emulator code, every optional dependency, or user-supplied files. Private cartridge and optional acceleration tests require their own fixtures and environments.

PokeSim remains an application for one owner or a trusted group. A reachable client can obtain a session and manage the library. Remote deployments need an authenticated TLS proxy or a restricted private network. Viewer-only game settings do not grant a restricted public spectator role. Backups include private ROMs and saves, and emulator subprocesses are not a security sandbox.
