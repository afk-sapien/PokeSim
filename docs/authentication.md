# Authentication and view links

PokeSim can run open or with accounts. `AUTH` picks the mode:

| `AUTH` | What happens |
| --- | --- |
| `none` | No login. Anyone who reaches the Library manages every adventure, ROM, save and backup. Put it behind a proxy that logs people in. |
| `accounts` | Everyone logs in. Admins manage the Library, members see their own adventures and the ones shared with them. |
| unset (`auto`) | A new library uses accounts. A library from before accounts stays open until an admin is set up, and shows a banner that says so. Setting up OpenID Connect or a trusted proxy also turns accounts on. |

The desktop app runs with `AUTH=none` unless you set `AUTH` yourself. For how admins,
members, invites and sharing work day to day, see [Users and sharing](users-and-sharing.md).

The examples use `pokesim.example.com`. Set `PUBLIC_URL=https://pokesim.example.com` and
keep the proxy's `Host` header, because PokeSim refuses other addresses.

## The first admin

With accounts on and no admin yet, PokeSim writes a one-time setup code to its log:

```sh
docker logs pokesim 2>&1 | grep 'one-time code'
```

Open `/setup`, enter the code and choose a username and a password of at least 10
characters. The code works once and lasts an hour. A restart prints a new one. Every
adventure that existed before accounts belongs to this first admin.

To skip the code, set `POKESIM_ADMIN_USER` and `POKESIM_ADMIN_PASSWORD` on the first start.
PokeSim creates that admin only while it has none, so later starts ignore both values.
Remove them once the admin exists.

Logins last 14 days. After five wrong passwords PokeSim makes each next try wait, up to 15
minutes, and says how long.

### A forgotten password

Run this on the machine that holds the data. It prints a new random password, ends every
session of that user, and works while PokeSim runs:

```sh
docker exec pokesim pokesim admin reset-password <username>
```

## Sign in with an identity provider

PokeSim speaks OpenID Connect, so Authelia, Authentik, Keycloak, Pocket ID and similar
providers can log people in. Register PokeSim as a confidential client with the redirect
address `https://pokesim.example.com/auth/oidc/callback`, then set:

| Setting | Meaning |
| --- | --- |
| `OIDC_ISSUER` | The provider's issuer address, such as `https://auth.example.com` |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | The client you registered |
| `OIDC_SCOPES` | Defaults to `openid profile email`. Add `groups` if your provider needs it. |
| `OIDC_GROUPS_CLAIM` | The claim that lists groups, `groups` by default |
| `AUTH_ADMIN_GROUP` | Group whose people become admins, `pokesim-admins` by default |
| `AUTH_MEMBER_GROUP` | Group whose people become members, `pokesim` by default |
| `OIDC_DEFAULT_ROLE` | `member` or `admin` for people in neither group. Empty by default, which refuses them. |
| `DISABLE_PASSWORD_LOGIN` | `true` hides the password form, so only the provider logs people in |

The login page then shows a button for the provider. Someone who already has a password can
link their provider sign-in from Settings and keep the same adventures.

## Log in through a trusted proxy

If your proxy already logs people in, PokeSim can take the username from a header the proxy
sets. Because anyone can send a header, PokeSim believes it only from the proxy's own
address and only with a shared secret:

| Setting | Meaning |
| --- | --- |
| `AUTH_PROXY_HEADER` | Header with the username, such as `Remote-User` |
| `AUTH_PROXY_GROUPS_HEADER` | Optional header with a comma separated group list, such as `Remote-Groups` |
| `AUTH_PROXY_SECRET` | At least 16 characters. The proxy sends it as `X-PokeSim-Proxy-Secret`. |
| `AUTH_TRUSTED_PROXIES` | The proxy's addresses or networks, comma separated |
| `AUTH_PROXY_DEFAULT_ROLE` | Role for people in neither group, `member` by default |

`AUTH_ADMIN_GROUP` and `AUTH_MEMBER_GROUP` work as above. PokeSim refuses to start if
`AUTH_TRUSTED_PROXIES` trusts every address or contains the network's default gateway, since
direct clients often arrive from the gateway's address. Trust the proxy container alone.

## View links

A view link is `/view/<adventure id>/`. It shows the screen, team, journal, progress and
statistics with every control hidden. Under `/view/` the server allows only `GET` and
`HEAD`, returns 403 for everything else, and never lists or exports saves.

With `AUTH=none`, anyone who has a view link can watch, so a proxy may leave `/view/` open.
Adventure ids are random, but they are not passwords.

With accounts, a plain view link needs a login by someone who may watch that adventure. To
let someone watch without an account, the owner makes a share link in Settings, under
Sharing. It looks like `/s/<token>`, can expire, and can be turned off at any time. Leave
`/s/` and `/view/` open at the proxy, and PokeSim checks the rest itself.

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

These rules suit `AUTH=none`, where Authelia alone decides who gets in. With accounts,
PokeSim checks every request, so one rule that covers the whole domain is enough.

Authelia needs its own address and a session cookie for a domain that covers both it and
PokeSim. For example, with Authelia at `auth.example.com`:

```yaml
session:
  cookies:
    - domain: example.com
      authelia_url: https://auth.example.com
      default_redirection_url: https://pokesim.example.com
```

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
assumes Traefik and Authelia (listening on port 9091) already share the `proxy` network,
and that Traefik's `websecure` entry point serves HTTPS.

The Authelia service needs `traefik.enable` too. Traefik reads the middleware from that
container's labels, and with `exposedByDefault=false` it ignores a container without it.
PokeSim then answers 404 and Traefik logs `middleware "authelia@docker" does not exist`.
The `authelia` router publishes the login page at the `authelia_url`.

```yaml
services:
  authelia:
    # image, configuration and volumes as in the Authelia documentation
    labels:
      traefik.enable: 'true'
      traefik.http.routers.authelia.rule: Host(`auth.example.com`)
      traefik.http.routers.authelia.entrypoints: websecure
      traefik.http.routers.authelia.tls: 'true'
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

With `AUTH=none`, PokeSim ignores the `Remote-*` headers. To use them for accounts, set
`AUTH_PROXY_HEADER: Remote-User` and `AUTH_PROXY_GROUPS_HEADER: Remote-Groups`, add the
secret header to the router with a `headers.customRequestHeaders` middleware, and list
Traefik's address in `AUTH_TRUSTED_PROXIES`.

Use your proxy's connection and bandwidth limits too. Each open view link keeps a live
stream running.
