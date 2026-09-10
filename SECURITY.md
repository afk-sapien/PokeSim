Security and support policy

Report a suspected vulnerability using [GitHub private vulnerability reporting](https://github.com/afk-sapien/PokiSim/security/advisories/new). Describe the affected release, deployment configuration, impact, and reproduction steps. Do not put security-sensitive details in a public issue. Never include ROMs, private saves, notification tokens, or passwords in a report.

The current 0.2.0 release-candidate line receives best-effort fixes. This is an experimental personal project with no guaranteed response time or stable-release support commitment. Keep deployments current and preserve backups before updating.

The application serves one owner or a trusted group. It has no built-in authentication. Remote access requires an authenticated TLS proxy or a private network. Protect every route and keep the backend port inaccessible to unauthenticated clients. With controls enabled, reachable clients can control, rewind, and restart the game.

`VIEWER_ONLY=1` disables game controls on the server. It does not authenticate viewers or limit streaming traffic. Use proxy limits for large audiences.

The runtime runs as an unprivileged user with a read-only application filesystem and ROM mount. Its data directory is writable. It does not need the Docker socket or privileged container access. Optional ntfy sends configured event information to the chosen notification service. Leave it disabled for an offline runtime.
