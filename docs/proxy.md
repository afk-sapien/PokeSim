Authenticated HTTPS deployment

This recipe protects the homepage, controls, API, feed, screenshots, and stream with the same authentication boundary. The application has no published backend port. Caddy terminates TLS and streams MJPEG without buffering. Docker Compose 2.24.4 or newer is required for the port reset used by the example.

Prepare the ROM, data ownership, and local game-data bundle using the README first.
This advanced recipe also needs `compose.proxy.yaml`, `deploy/Caddyfile`, and
`deploy/proxy.env.example` from the source archive matching your installed release.
If you installed only the prebuilt release assets, copy those files into your
installation directory, preserving the `deploy` folder. The
[rc31 source archive](https://github.com/afk-sapien/PokeSim/releases/download/v0.2.0rc31/pokesim-0.2.0rc31.tar.gz)
contains them. Stop the direct deployment before switching:

```sh
docker compose stop
cp deploy/proxy.env.example .env.proxy
chmod 600 .env.proxy
docker run --rm -it caddy:2.11.4-alpine caddy hash-password
```

Enter a password interactively. Copy the resulting hash into `AUTH_HASH` in `.env.proxy`, using single quotes around the hash. Set `AUTH_USER`, `ROM_FILE`, and `DATA_PATH`. Copy the exact `POKESIM_IMAGE` setting from your working `.env` too, since `.env.proxy` replaces it for these commands. For the localhost example, keep the supplied address and port defaults.

```sh
docker compose --env-file .env.proxy -f compose.proxy.yaml up -d
```

Visit `https://localhost:9443`. Caddy uses its local CA for localhost. Export the root certificate from the proxy and add it to the specific client's trust store before connecting. Do not disable certificate verification to work around the local CA. The automated test uses an explicit CA file with hostname verification enabled.

To export that root certificate:

```sh
docker compose --env-file .env.proxy -f compose.proxy.yaml cp proxy:/data/caddy/pki/authorities/local/root.crt ./pokesim-local-ca.crt
```

For a real domain, set `SITE_ADDRESS` to your domain, set `PUBLIC_URL` to its HTTPS URL, choose the desired host bind address, and map ports 80 and 443 by setting the proxy port variables accordingly. Point DNS at the host and route those two ports to Caddy. Caddy can then obtain a publicly trusted certificate. The localhost acceptance test does not prove your own DNS or firewall configuration.

The backend network is internal and has no external route. Optional ntfy delivery needs a deliberately configured outbound network for the app. Adding an outbound network does not require publishing its backend port. Keep the direct Compose service stopped so an old direct container cannot bypass the proxy.

Basic authentication requires TLS. Feed readers must support it. Notification click links will ask for authentication, and external notification attachment fetchers may not be able to access protected resources. A viewer-only setting still works behind the proxy and prevents all control operations even for authenticated viewers.

The proxy enforces a 24-hour stream lifetime. The browser retries after a failed stream and refreshes the stream when the state connection recovers. Shutdown bounds Uvicorn's stream drain to five seconds so an open viewer does not keep the container alive indefinitely.

Use the same Compose file and environment file for stop, logs, and future upgrades. Rotate the hash when changing the password. The supplied example never exposes an unauthenticated game control port.
