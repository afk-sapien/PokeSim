# Security and support policy

Report a suspected vulnerability using [GitHub private vulnerability reporting](https://github.com/afk-sapien/PokeSim/security/advisories/new). Describe the affected release, deployment configuration, impact, and reproduction steps. Do not put security-sensitive details in a public issue. Never include ROMs, private saves, notification tokens, or passwords in a report.

Only the latest release receives best-effort fixes. This is an experimental personal project with no guaranteed response time or stable-release support commitment. Keep deployments current and preserve backups before updating.

The application serves one owner or a trusted group. It has no built-in login or per-user permissions. Anyone who can reach the application can obtain a browser session and manage the library, including its ROMs, saves, imports, and downloadable backups. CSRF tokens and browser-origin checks prevent unrelated websites from issuing requests. They do not authenticate a person.

Desktop and default Compose deployments bind to loopback. For remote access, use the [authenticated HTTPS proxy](docs/proxy.md) or a private network restricted to trusted users. Protect every route and keep the backend port inaccessible to unauthenticated clients. Do not forward the plain application port to the internet. Set `PUBLIC_URL` to the exact browser origin, including the port when nonstandard. The legacy launcher now enforces that address too.

An adventure's viewer-only setting disables its game controls. It does not restrict library administration or protect other adventures. Legacy `VIEWER_ONLY=1` also is not authentication. PokeSim does not provide an untrusted public spectator role. Use proxy connection and bandwidth limits for shared viewing.

The supplied application container runs as an unprivileged user with a read-only application filesystem, dropped capabilities, and no new privileges. Its data directory is writable and contains private ROMs and saves. Restrict host filesystem permissions and backup access to the owner. Do not mount the Docker socket or unrelated home directories. A native Python installation runs with your account's permissions. Emulator subprocesses are not an operating-system sandbox.

Import only backups and saves you trust. Archive paths, expanded sizes, and backup checksums are checked, but a checksum is not proof of who created a backup. Do not use the import feature as a malware scanner for arbitrary emulator states or databases. Backups include private game files and are not encrypted.

Game workers listen only on loopback and require a per-process bearer credential. The browser proxy allows only public game routes. Optional ntfy sends configured event information to the chosen notification service. The proxy recipe permits outbound reference-data downloads without publishing an application port. Prepare reference data first and remove that outbound network when an offline runtime is required.

Security tests cover request origins, CSRF sessions, private worker routes, and archive paths. Dependency advisories are checked in CI. Container scans block high and critical findings with available fixes. Unfixed upstream OS advisories remain and are described in the [hardening report](docs/validation/security-hardening-20260919.md). These checks reduce risk and do not guarantee that the application or its native dependencies are free of vulnerabilities.
