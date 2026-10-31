# App store templates

Drafts for home server app stores. None of them has been submitted.
Each one runs the same image as `compose.quickstart.yaml`, keeps everything in one
folder mounted at `/data`, serves the browser UI on port 8930 and takes the same
optional ntfy settings.

| Store | Files | Data folder |
| --- | --- | --- |
| Unraid Community Applications | `unraid/pokesim.xml` | `/mnt/user/appdata/pokesim` |
| CasaOS (Big Bear layout) | `casaos/docker-compose.yml` | `/DATA/AppData/pokesim/data` |
| Umbrel | `umbrel/pokesim/` | the app's `data` folder |
| TrueNAS community apps | `truenas/pokesim/` | an ixVolume or a host path |

## Set PUBLIC_URL

PokeSim refuses any request whose host differs from `PUBLIC_URL`. Set it to the
exact address you type in the browser, such as `http://nas.local:8930`.
A wrong value shows "Use the configured PokeSim address". Umbrel sets it to
`http://<device name>:8930`, so open it through that name rather than the IP address.

## Users and permissions

All four drop every capability, block privilege escalation and mount a 256 MB `/tmp`.
Unraid, CasaOS and Umbrel also make the root filesystem read-only. The user differs
by store:

- **Unraid and CasaOS** run as user 0 because they create the data folder as root.
  With no capabilities, that user can only write to folders it owns.
- **Umbrel** runs as 1000:1000, which owns the app's data folder.
- **TrueNAS** runs as 568:568 (`apps`), and its permissions step sets the owner of the
  data folder before the first start.

## Before submitting

1. Submit from a release tag. `tools/release_version.py` moves the version in every
   template with the rest of the release, so the tag's templates name its image.
2. Check that the release image covers linux/arm64 if the store lists arm64.
3. Umbrel needs a 256x256 icon and gallery images uploaded to its gallery repository,
   and pins images by digest (`image@sha256:...`).
4. TrueNAS: copy `truenas/pokesim/` into `ix-dev/community/` and run that repository's
   app test, which renders the template against its current library.
5. CasaOS: add a PNG icon. Some dashboards do not draw SVG icons.

The Compose files and the Unraid flags were started locally with the release image.
None was installed on the store's own system, so check one install on each before
submitting, especially that the Umbrel app proxy passes the browser's host through.
