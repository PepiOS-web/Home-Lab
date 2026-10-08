# A9/V720 hardened local adapter

This directory prepares a local, security-hardened copy of
`intx82/a9-v720`. It is pinned to the audited commit
`a795f8b4e17a03394d66cdde1d2633dd08e6be87`.

The upstream project does not declare a license. For that reason its source is
not copied into this repository. `prepare-upstream.sh` downloads the exact
audited archive, verifies its SHA-256 hash, extracts only `src/` and applies the
reviewed local patch. The generated `_upstream/` directory is ignored by Git.

Do not deploy this service until the camera has a reserved IP and the router or
firewall can block its Internet and lateral LAN access.

## Security changes

- HTTP binds only to the explicitly configured camera-side address
  (A9_HTTP_BIND_HOST:18080 in isolated-AP mode).
- Camera protocol TCP/UDP binds to one explicitly configured HomeLab address.
- HTTP camera-registration requests accept only the reserved camera IP.
- TCP and UDP camera traffic accept only the reserved camera IP.
- `/dev/*` video, audio, snapshot and listing endpoints require Basic auth.
- Frame queues are bounded to reduce memory-exhaustion risk.
- The server path no longer imports OpenCV, Pillow, NumPy, tqdm or xmltodict.
- The container runs as UID/GID 10001, read-only, without Linux capabilities,
  with `no-new-privileges` and resource limits.

Basic auth is a second local control; Caddy must provide HTTPS for every human
viewer. Credentials must never cross the LAN over plain HTTP.

## Preparation on Ubuntu

Required host tools: `curl`, `unzip`, `git`, `python3`, Docker and Compose.

```bash
cd /srv/data/compose/a9-v720-hardened
./prepare-upstream.sh
cp .env.example .env
chmod 600 .env
```

Replace every placeholder in `.env`. Generate the password locally, for
example with `openssl rand -base64 32`.

Validate before starting:

```bash
docker compose config
docker compose build --pull
docker compose up -d
docker compose ps
docker compose logs --tail=100 a9-v720
```

The service deliberately uses host networking because the reverse-engineered
camera protocol includes direct TCP/UDP callbacks. Compensating controls are
the explicit bind address, application IP allowlist, the dedicated `cam_ap`
network and its nftables isolation rules. Do not start it until those network
controls are ready.

## Still required

- Caddy route for an authenticated viewer URL, if browser access is wanted.
- Local DNS overrides for the Naxclow domains (provided by the dedicated
  `dnsmasq-camera` service in the isolated-AP deployment).
- MQTT listener restricted to the camera interface and Naxclow topic ACL.
- Packet-capture verification that the camera has no Internet path.
