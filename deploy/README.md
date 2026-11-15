# Hosting climpact.app: runbook

How to set up the hosted climpact web app from nothing: one DigitalOcean Droplet running
Docker Compose, reached only through a Cloudflare Tunnel (#12, #123). Written so that
anyone with the DigitalOcean and Cloudflare accounts can repeat it, for example to move the
service to WMO's accounts. Budget **under an hour**, most of it waiting for the Droplet to
finish its first boot.

```
visitor ──https──▶ Cloudflare edge ◀──tunnel (outbound only)── cloudflared ──▶ web:8000
                   (WAF, rate limit)                            └──── the Droplet ────┘
```

The Droplet accepts **no inbound connections**. `cloudflared` dials out to Cloudflare, and
Cloudflare sends the site's traffic back down that connection. Nobody can reach the server
by its IP address, so nobody can get around Cloudflare.

| File | What it is |
| --- | --- |
| `cloud-init.yaml` | The Droplet's user data: the `deploy` user, Docker, swap, SSH hardening, automatic security updates, `/opt/climpact` and the helper commands |
| `compose.yaml` | The stack: `web`, `worker`, `db` (Postgres 16), `purge`, `cloudflared` (#121) |
| `.env.example` | The stack's settings. The real `.env` exists only on the Droplet |

The design and the reasons behind it are in `TECHNICAL.md` › Deployment.

> **The app image comes from a GitHub Release.** `ghcr.io/geoffwalmsley/climpact-web` is
> pushed only when a release `vX.Y.Z` is published (#122). Until the first release
> (**v0.1.0**, #131) exists there is nothing to run. You can do steps 1–5 now. Step 6
> (`docker compose up`) has to wait for the release.

## What you need

- The DigitalOcean account, and the Cloudflare account that holds the `climpact.app` zone
  (free plan; DNS already on Cloudflare).
- An SSH key pair on your computer (`ssh-keygen -t ed25519` if you have none). Its public
  half (`~/.ssh/id_ed25519.pub`) is uploaded to DigitalOcean.
- Your computer's public IP address, to let SSH in during the setup
  (DigitalOcean's firewall page has a "My IP" option, or use `curl -4 https://icanhazip.com`).

## 1. Create the Droplet with the user data (about 10 min)

User data can be given **only when a Droplet is created**. *Rebuild* reinstalls the image
but keeps the user data the Droplet was created with, and you cannot add or change it
afterwards (DigitalOcean: "You cannot modify user data after a Droplet is created"). If a
Droplet already exists without this user data, as the empty one made before this runbook
did, **destroy it and create a new one**. Do not rebuild it.

1. If an old Droplet exists: open it › **Destroy** › *Destroy this Droplet*. Note its
   region first. Nothing on it is kept.
2. **Create › Droplets**, then:
   - **Region:** the one nearest the expected users. Use the old Droplet's region if
     there was one.
   - **Image:** OS › **Ubuntu 24.04 (LTS) x64**.
   - **Size:** Droplet Type **Basic**, CPU options **Regular**, **$12/mo: 2 GB / 1 CPU,
     50 GB SSD**. 1 GB is too small (see `TECHNICAL.md` › Deployment › Size and memory).
   - **Authentication:** **SSH Key**. Select or upload your public key. Do not use a
     password. The key ends up on the `deploy` user, and root cannot log in over SSH.
   - **Additional options:** tick **Monitoring** (free). Tick **Add initialization scripts
     (free)** and paste the whole of `deploy/cloud-init.yaml` (from the release's tag, or
     `main`) into the box. It must start with `#cloud-config`.
   - **Hostname:** `climpact`. **Tags:** `climpact`. **Project:** create or choose a
     project called `climpact`.
   - **Backups:** optional (+20%). Jobs expire after 7 days and the app keeps nothing
     else, so a lost Droplet is rebuilt with this runbook rather than restored.
3. **Create Droplet**, and copy its public IPv4 address.

## 2. Close it with a Cloud Firewall (about 5 min)

**Networking › Firewalls › Create Firewall**:

- **Name:** `climpact`.
- **Inbound rules:** delete the default SSH rule, then add **one temporary rule** for the
  setup: *SSH*, TCP 22, source **your IP address only** (not "All IPv4"). You delete it in
  step 8, so that the firewall ends up with **no inbound rules at all**.
- **Outbound rules:** keep the defaults (all TCP, all UDP and ICMP to everywhere).
  The tunnel, image pulls and security updates need them.
- **Apply to Droplets:** the tag `climpact`, so a Droplet created again later is covered
  from its first boot.

Also check **Networking › Domains**: DigitalOcean must not hold DNS records for
`climpact.app`. The zone lives on Cloudflare.

## 3. Check the first boot (about 10 min, mostly waiting)

The first boot installs updates and Docker, so give it 5–10 minutes. Then:

```sh
ssh deploy@<droplet-ip>
cloud-init status --wait --long      # wait for "status: done"; "error" means read the log
```

If it reports an error, read `/var/log/cloud-init-output.log`. Lines starting
`climpact-bootstrap:` come from this setup. Then check:

```sh
docker version && docker compose version     # works without sudo: deploy is in the docker group
swapon --show                                # /swapfile, 2G
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|allowusers) '
                                             # no / no / deploy
ls -la /opt/climpact                         # compose.yaml and .env.example, owned by deploy
systemctl list-timers climpact-image-prune.timer apt-daily-upgrade.timer
```

`ssh root@<droplet-ip>` must be refused.

## 4. Create the Cloudflare Tunnel (about 10 min)

In the Cloudflare dashboard, open **Zero Trust** (the first visit asks for a team name, and
the free plan is enough), then **Networks › Tunnels**:

1. **Create a tunnel** › type **Cloudflared** › name `climpact` › **Save tunnel**.
2. On *Install and run a connector*, choose **Docker**. The page shows a command ending in
   `--token eyJ...`. **Copy only the token** (the long `eyJ...` string). It is the
   `TUNNEL_TOKEN` for step 5. Don't run the command: Compose runs `cloudflared`. Treat
   the token like a password, because anyone holding it can serve the site.
3. **Next** › *Route traffic* › **Public hostname** (shown as *Published application
   routes* in newer dashboards):
   - **Subdomain:** empty. **Domain:** `climpact.app`. **Path:** empty.
   - **Service:** type **HTTP**, URL **`web:8000`**.
   - **Save**. Cloudflare creates the proxied DNS record (a CNAME to
     `<tunnel-id>.cfargotunnel.com`) itself.

   If it says a record already exists, go to the zone's **DNS › Records**, delete the
   existing `A`, `AAAA` or `CNAME` record for `climpact.app`, and save the route again.
   **No DNS record may point at the Droplet's IP.** A record like that would publish the
   origin's address. (`www.climpact.app` and its redirect are set up in #124.)

The tunnel shows as *Inactive* until `cloudflared` runs in step 6.

## 5. Make the `.env` with the secrets (about 2 min)

On the Droplet, as `deploy`:

```sh
climpact-init-env
```

It copies `.env.example` to `/opt/climpact/.env` (mode 0600, owned by `deploy`). It
generates the Django secret key and the Postgres password on the server, turns on the
`tunnel` profile (`COMPOSE_PROFILES=tunnel`), and asks for the tunnel token from step 4.
The token is pasted at a hidden prompt, so it stays out of the shell history. The command
prints which settings are set, never their values, and it never changes a value that is
already set. Run it again at any time. The secrets exist only in that file: not in the
repository, not in the user data, not at DigitalOcean.

`CLIMPACT_IMAGE` still reads `...:X.Y.Z` at this point. Step 6 sets it. The other settings
in `.env` (allowed host, upload limit, retention) have the right defaults for
`climpact.app`, and each one is described in the file.

## 6. Start the stack: after the release is published (about 5 min)

**Waits for the first GitHub Release (v0.1.0, #131).** Check that the release exists at
<https://github.com/geoffwalmsley/climpactpy/releases>, and that its *Release* workflow has
finished (it pushes the image).

```sh
climpact-use v0.1.0
cd /opt/climpact && docker compose up -d --wait
docker compose ps        # db, web, worker, purge, cloudflared up; migrate exited (0)
```

`climpact-use vX.Y.Z` is how the image tag is pinned. It fetches `compose.yaml` and
`.env.example` from the release's git tag, sets
`CLIMPACT_IMAGE=ghcr.io/geoffwalmsley/climpact-web:X.Y.Z` in `.env`, and pulls that image.
The Compose file and the image therefore always come from the same release. You can also
edit the `CLIMPACT_IMAGE` line by hand. The image tag is the version without the `v`
(`0.1.0`). `latest` follows the last final release, but a pinned version is the better
choice, because the site then changes only when someone deploys a new one.

If the pull fails with *denied* or *unauthorized*, the package may still be private (a
package created by a workflow can start private): on GitHub open the profile's
**Packages › climpact-web › Package settings › Change visibility › Public**, once.

In Cloudflare the tunnel should now show as **Healthy**.

## 7. Smoke test (about 5 min)

From your computer:

```sh
curl -sS https://climpact.app/healthz
# {"status": "ok", "database": "ok", "version": "0.1.0", ...}: the release's version
curl -sSI http://climpact.app/ | head -n 3      # a redirect to https://
```

In a browser at <https://climpact.app>: start a station analysis with the **sample data**
(Sydney), run the quality checks, then the indices with plots. Open the results, and
download one index CSV and the zip. If anything fails, look at the logs on the Droplet:
`docker compose logs --tail 100 web worker`.

## 8. Shut SSH and check the IP answers nothing (about 2 min)

1. **Networking › Firewalls › climpact**: delete the temporary SSH rule. **Inbound rules
   must be empty.**
2. From your computer, every one of these must time out:
   ```sh
   curl --max-time 5 http://<droplet-ip>/
   curl --max-time 5 -k https://<droplet-ip>/
   nc -vz -w 5 <droplet-ip> 22
   ```
   Also check `https://climpact.app/healthz` again: it must still answer. It goes through
   the tunnel, so the firewall doesn't touch it.

Done. Record the date, the Droplet's region and the release in #123.

## Running it

**Update to a new release** (until #126 deploys releases automatically): open SSH as in
step 2, then

```sh
climpact-use vX.Y.Z && cd /opt/climpact && docker compose up -d --wait
```

and close SSH again. Migrations run on their own (the `migrate` service) before `web` and
`worker` start. **Roll back** the same way with the earlier version. Release images stay on
ghcr.io, and a database migration that cannot be undone will say so in the release notes.

**Get a shell when the firewall is closed** (break glass):
- Usual way: add the temporary SSH rule for your IP (step 2), then `ssh deploy@<ip>`.
- DigitalOcean's **Droplet Console** (in the browser) also connects over SSH, but from
  DigitalOcean's own addresses, which are not published, so it works only while port 22
  is open to everyone. Log in as `deploy`. Prefer the rule for your own IP.
- If SSH itself is broken: **Access › Reset root password** (DigitalOcean emails a
  password), then the **Recovery Console**, which is the Droplet's screen and keyboard and
  needs no network. Root can log in there, though not over SSH.

**Logs:** `docker compose logs -f web worker` (rotated at 10 MB × 3 per container).
Bootstrap log: `/var/log/cloud-init-output.log`. DigitalOcean's Monitoring graphs CPU,
memory and disk.

**Automatic updates:** Ubuntu's security updates and Docker's packages install every day
(`unattended-upgrades`). When an update needs a reboot, the Droplet reboots at 03:30 UTC,
and the stack comes back by itself (`restart: unless-stopped`). Docker's `live-restore`
keeps the containers running while Docker itself is upgraded. A weekly timer
(`climpact-image-prune.timer`) deletes images no container has used for 30 days. Expired
jobs are purged by the stack itself (the worker every hour, the `purge` service daily).
Nothing updates the app: that is a release (#126).

**Rotate a secret:**
- Tunnel token: in Cloudflare open the tunnel › **Refresh token** (or create a new
  tunnel), put the new token in `.env` (`nano /opt/climpact/.env`), then
  `docker compose up -d`.
- Django secret key: replace it in `.env` and `docker compose up -d`. This signs out any
  open sessions, nothing else.
- Postgres password: the database keeps the password it was created with, so changing
  `.env` alone breaks the app. Change it inside Postgres first
  (`docker compose exec db psql -U climpact -c "ALTER USER climpact PASSWORD '<new>'"`),
  then in `.env`, then `docker compose up -d`.

**Start again from nothing:** destroy the Droplet and repeat steps 1–3 and 5–8. The
Cloud Firewall (by tag) and the tunnel stay. The tunnel's token is shown again under the
tunnel's **Configure** page (the Docker install command), or use **Refresh token**.

## Moving it to other accounts (handover)

The same steps work in WMO's own DigitalOcean and Cloudflare accounts: the zone moves to
WMO's Cloudflare account (or the domain is transferred), and the tunnel, firewall and
Droplet are created there from this runbook. Then destroy the old Droplet and delete the
old tunnel. No secret has to be carried over, because `climpact-init-env` makes new ones.
Jobs are short-lived, so no data needs moving either.
