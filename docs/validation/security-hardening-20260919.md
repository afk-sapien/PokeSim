Security hardening validation, September 19, 2026

This pass reviewed the Adventure Library manager, private worker proxy, browser request boundaries, legacy launcher, archive imports and restores, container defaults, and authenticated proxy deployment.

Changes:

- Replaced the worker proxy's path blacklist with an explicit public-route allowlist. An encoded single-dot path previously passed the blacklist and was normalized by HTTPX into a private worker route. Regression tests cover encoded dots, separators, query delimiters, fragments, and private endpoints across GET, POST, and HEAD.
- Added content security and same-origin resource policies. Real Chromium tests verify that the library's scripts and settings still work while injected inline scripts are blocked.
- Added Host, Origin, and Fetch Metadata checks to the legacy launcher, with matching health-probe behavior. The manager now rejects invalid public origins before opening its data directory.
- Rejected archive paths containing Windows device names, ambiguous components, control characters, or existing symbolic links. Backup member checksums now stream from disk instead of loading a whole member into memory.
- Restricted the Caddy container to a read-only root filesystem, no new privileges, and its required port-binding capability. Corrected the proxy's library data-directory example and documented the distinction between viewer-only controls and library administration.
- Added locked runtime dependency auditing and an actual authenticated TLS deployment check to CI.

Local validation:

- Full working-tree Python suite with Chromium enabled: 1,213 passed, 31 optional checks skipped. The working tree also contained separately prepared publishing changes, which this security change preserves without committing.
- Focused security and affected-route suite: 123 passed.
- Browser JavaScript checks, documentation links, workflow linting, and patch whitespace checks passed.
- A local application image built successfully. Disposable legacy and library Compose deployments passed startup, health checks, saves, shutdown, and restart.
- The disposable Caddy deployment passed certificate and hostname verification, missing and invalid authentication on every tested route, CSRF checks, cross-origin rejection, private-route rejection, and inspection confirming no published backend port. Test containers and volumes were removed afterward.
- pip-audit 2.10.1 found no known advisories in 27 locked runtime packages selected for the audit environment. A separate installed-environment scan covered 35 third-party packages with no advisories. The editable application itself was excluded from that package advisory lookup.
- Gitleaks 8.30.1 scanned 117 commits reachable through local refs. Its 11 findings were reviewed and identified as game trade fingerprints, the `pokedex-milestones-v1` storage key, and Pokémon Secret Key objective text. No credential was identified by that scan.

Limits:

This is a targeted engineering review, not an independent penetration test or a guarantee of zero vulnerabilities. Package advisory results are a point-in-time check, not a full audit of native emulator code, operating-system packages, every optional dependency, or user-supplied files. Private cartridge and optional acceleration tests require their own fixtures and environments.

PokeSim remains an application for one owner or a trusted group. A reachable client can obtain a session and manage the library. Remote deployments need an authenticated TLS proxy or a restricted private network. Viewer-only game settings do not grant a restricted public spectator role. Backups include private ROMs and saves, and emulator subprocesses are not a security sandbox.
