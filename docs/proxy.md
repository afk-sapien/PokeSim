Authenticated HTTPS deployment

This recipe protects the homepage, controls, API, feed, screenshots, and stream with the same authentication boundary. The application has no published backend port. Caddy terminates TLS and streams MJPEG without buffering. Docker Compose 2.24.4 or newer is required for the port reset used by the example.

Prepare the application data directory and its ownership using the README first.
This advanced recipe also needs `compose.proxy.yaml`, `deploy/Caddyfile`,
`deploy/proxy.env.example`, and the entire `deploy/proxy` folder from the source archive matching your installed release.
If you installed only the prebuilt release assets, copy those files into your
installation directory, preserving the `deploy` folder. The
source archive for the same release contains them. Stop the direct deployment before switching:

```sh
docker compose stop
cp deploy/proxy.env.example .env.proxy
chmod 600 .env.proxy
docker run --rm -it --network none caddy:2.11.4-alpine caddy hash-password
```

Enter a password interactively. Copy the resulting hash into `AUTH_HASH` in `.env.proxy`, using single quotes around the hash. Set `AUTH_USER` and `DATA_PATH`. Use the existing Adventure Library directory, normally `./pokesim-app`. Do not point it at a legacy single-adventure `./data` folder. Import legacy saves through the library instead. Copy the exact `POKESIM_IMAGE` setting from your working `.env` too, since `.env.proxy` replaces it for these commands. For the localhost example, keep the supplied address and port defaults.

```sh
docker compose --env-file .env.proxy -f compose.proxy.yaml build --pull proxy
docker compose --env-file .env.proxy -f compose.proxy.yaml up -d
```

The first command builds the proxy locally from Caddy 2.11.4 with a current Go toolchain and locked security updates for its dependencies. It needs internet access and may take several minutes. This avoids older Go dependencies still present in the official Caddy binary. Repeat the build when updating the source recipe. The application image is still the prebuilt image selected by `POKESIM_IMAGE`.

Visit `https://localhost:9443`. Caddy uses its local CA for localhost. Export the root certificate from the proxy and add it to the specific client's trust store before connecting. Do not disable certificate verification to work around the local CA. The automated test uses an explicit CA file with hostname verification enabled.

To export that root certificate:

```sh
docker compose --env-file .env.proxy -f compose.proxy.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./pokesim-local-ca.crt
```

For a real domain, set `SITE_ADDRESS` to your domain, set `PUBLIC_URL` to its HTTPS URL, choose the desired host bind address, and map ports 80 and 443 by setting the proxy port variables accordingly. Point DNS at the host and route those two ports to Caddy. Caddy can then obtain a publicly trusted certificate. The localhost acceptance test does not prove your own DNS or firewall configuration.

The backend network is internal. A separate outbound network lets the app download its pinned reference-data archive on first setup. Neither network publishes an application port. Remove the app's `outbound` network after preparing reference data if you require an offline runtime. Optional ntfy also needs outbound access. Keep the direct Compose service stopped so an old direct container cannot bypass the proxy.

Basic authentication requires TLS. Feed readers must support it. Notification click links will ask for authentication, and external notification attachment fetchers may not be able to access protected resources. Every authenticated user has library administration access. An adventure's viewer-only setting disables that game's controls, but does not restrict library administration or other adventures. Share credentials only with trusted people.

The proxy enforces a 24-hour stream lifetime. The browser retries after a failed stream and refreshes the stream when the state connection recovers. The library allows up to 60 seconds to drain requests during shutdown, within Compose's 90-second stop grace period.

Use the same Compose file and environment file for stop, logs, and future upgrades. Rotate the hash when changing the password. The supplied example never exposes an unauthenticated game control port.
