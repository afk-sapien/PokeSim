# Authentication and view links

PokeSim has no login. Anyone who reaches the Library can manage every adventure, its ROMs,
saves and backups. Put it behind a proxy that authenticates people, such as
[Authelia](https://www.authelia.com), and open only view links without a login.

A view link is `/view/<adventure id>/`. Copy one with **Copy view link** on an adventure's
live page. It shows the screen, team, journal, progress and statistics with every control
hidden. Under `/view/` the server allows only `GET` and `HEAD`, returns 403 for everything
else, and never lists or exports saves. `/view/` is the only path that is safe to open
without authentication. Everything else, including `/`, `/games/`, `/api/v1/` and `/static/`,
must stay behind the login. Adventure ids are random, but they are not passwords: anyone who
has a link can watch that adventure.

The examples use `pokesim.example.com`. Set `PUBLIC_URL=https://pokesim.example.com` and
keep the proxy's `Host` header, because PokeSim refuses other addresses.

## Keep the port private

PokeSim's port must be reachable only through the proxy. With Compose, remove the `ports:`
entry and attach the service to the proxy's network, so the proxy is the only way in:

```yaml
services:
  pokesim:
    # no ports: entry
    environment:
      PUBLIC_URL: https://pokesim.example.com
    networks: [proxy]
networks:
  proxy:
    external: true
```

## Authelia rules

Authelia checks `access_control` rules from top to bottom and uses the first rule that
matches. Keep `default_policy: deny`, so anything the rules do not name is refused.

### Public view links

Anyone can open a view link. Everything else needs a login.

```yaml
access_control:
  default_policy: deny
  rules:
    - domain: pokesim.example.com
      resources: ['^/view/.*$']
      policy: bypass
    - domain: pokesim.example.com
      policy: two_factor   # or one_factor
```

### Logged-in watchers

Members of `pokesim-admins` get the whole Library. Other logged-in users can only open view
links. People who are not logged in get nothing.

```yaml
access_control:
  default_policy: deny
  rules:
    - domain: pokesim.example.com
      subject: 'group:pokesim-admins'
      policy: two_factor
    - domain: pokesim.example.com
      resources: ['^/view/.*$']
      policy: one_factor
```

## Traefik forward authentication

A minimal Compose setup where Traefik asks Authelia about every request to PokeSim. It
assumes Traefik and Authelia (listening on port 9091) already share the `proxy` network.

```yaml
services:
  authelia:
    # image, configuration and volumes as in the Authelia documentation
    labels:
      traefik.http.middlewares.authelia.forwardAuth.address: http://authelia:9091/api/authz/forward-auth
      traefik.http.middlewares.authelia.forwardAuth.trustForwardHeader: 'true'
      traefik.http.middlewares.authelia.forwardAuth.authResponseHeaders: Remote-User,Remote-Groups,Remote-Name,Remote-Email
  pokesim:
    labels:
      traefik.enable: 'true'
      traefik.http.routers.pokesim.rule: Host(`pokesim.example.com`)
      traefik.http.routers.pokesim.entrypoints: websecure
      traefik.http.routers.pokesim.tls: 'true'
      traefik.http.routers.pokesim.middlewares: authelia@docker
      traefik.http.services.pokesim.loadbalancer.server.port: '8000'
```

Use your proxy's connection and bandwidth limits too. Each open view link keeps a live
stream running.
