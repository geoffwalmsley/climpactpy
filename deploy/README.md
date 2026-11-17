# Hosting climpact.app: runbook

How to set up the hosted climpact web app from nothing: one DigitalOcean Droplet running
Docker Compose, reached only through a Cloudflare Tunnel (#12, #123). Written so that
anyone with the DigitalOcean and Cloudflare accounts can repeat it, for example to move the
service to WMO's accounts. Budget **under an hour**, most of it waiting for the Droplet to
finish its first boot.

```
visitor ──https──▶ Cloudflare edge ◀──tunnel (outbound only)── cloudflared ──▶ web:8000
                   (WAF, rate limit)                              │   /_deploy ──▶ deploy-hook:9000
                                                                  └──── the Droplet ────┘
```

The Droplet accepts **no inbound connections**. `cloudflared` dials out to Cloudflare, and
Cloudflare sends the site's traffic back down that connection. Nobody can reach the server
by its IP address, so nobody can get around Cloudflare.

| File | What it is |
| --- | --- |
| `cloud-init.yaml` | The Droplet's user data: the `deploy` user, Docker, swap, SSH hardening, automatic security updates, `/opt/climpact` and the helper commands |
| `compose.yaml` | The stack: `web`, `worker`, `db` (Postgres 16), `purge`, `cloudflared` (#121) |
| `.env.example` | The stack's settings. The real `.env` exists only on the Droplet |
| `cloudflare/*.txt` | The Cloudflare rule expressions, pasted into the dashboard (see [Cloudflare edge settings](#cloudflare-edge-settings)) |
| `check-edge.sh` | Checks the edge settings from your own computer |
| `update.sh` | Deploys a release on the Droplet (`/opt/climpact/update.sh X.Y.Z`): files, image, migrations, health check, automatic rollback. The only way to update or roll back |
| `deploy-hook.py` | The deploy hook: the `deploy-hook` service that the release workflow calls at `https://climpact.app/_deploy` (see [Deploy on release](#deploy-on-release)) |
| `call-hook.sh` | The workflow's side: signs and sends the deploy request, then waits for `/healthz` to report the version |

The design and the reasons behind it are in `TECHNICAL.md` › Deployment.

> **The app image comes from a GitHub Release.** `ghcr.io/geoffwalmsley/climpact-web` is
> pushed only when a release `vX.Y.Z` is published (#122). The first was **v0.1.0**
> (2026-11-15).

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
     `main`) into the box. It must start with `#cloud-config`. Copy it from the file's
     *Raw* view on GitHub, or with
     `curl -fsSL https://raw.githubusercontent.com/geoffwalmsley/climpactpy/vX.Y.Z/deploy/cloud-init.yaml | pbcopy`.
     The file is plain ASCII on purpose: a paste that garbles even one character makes
     cloud-init ignore the whole file (step 3 shows it as `recoverable_errors`).
   - **Hostname:** `climpact`. **Tags:** `climpact`. **Project:** create or choose a
     project called `climpact`.
   - **Backups:** leave them **off** (decision in [Backups](#backups)). Jobs expire after
     7 days and the app keeps nothing else, so a lost Droplet is rebuilt with this runbook
     rather than restored.
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

`status: done` must come with **no** `recoverable_errors`. A warning like *Failed loading
yaml blob … empty cloud config* means the pasted user data was garbled and nothing was set
up (root can still log in, and there is no `deploy` user): destroy the Droplet and create
it again with a clean paste.

If it reports an error, read `/var/log/cloud-init-output.log`. Lines starting
`climpact-bootstrap:` come from this setup. Then check:

```sh
docker version && docker compose version     # works without sudo: deploy is in the docker group
swapon --show                                # /swapfile, 2G
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|allowusers) '
                                             # no / no / deploy
ls -la /opt/climpact                         # update.sh, compose.yaml, .env.example, deploy-hook.py
                                             # owned by deploy, and hook/ (owner 10001, group deploy)
systemctl list-timers climpact-image-prune.timer apt-daily-upgrade.timer
systemctl status climpact-deploy.path        # active (waiting): the deploy hook's watcher
```

`ssh root@<droplet-ip>` must be refused.

## 4. Create the Cloudflare Tunnel (about 10 min)

In the Cloudflare dashboard, open **Zero Trust** (the first visit asks for a team name, and
the free plan is enough), then **Networks › Tunnels**. The screens below are as of
November 2026; Cloudflare renames them from time to time.

1. **Create Tunnel** › name `climpact` › **Create Tunnel**. Note the **Tunnel ID** it shows
   (a UUID; not a secret).
2. Under *Setup Environment* choose **Docker**. *Run tunnel with Docker* shows a command
   ending in `--token eyJ...`. Copy it with the copy button and keep **only the token** (the
   long `eyJ...` string) somewhere temporary: it is the `TUNNEL_TOKEN` for step 5. Don't run
   the command: Compose runs `cloudflared`. Treat the token like a password, because anyone
   holding it can serve the site.
3. **Leave this page open.** *Continue* stays greyed out until the connector has connected,
   which happens in step 6. Do steps 5 and 6 now, then come back to step 4.4.
4. After step 6 the page shows the connection and *Continue* unlocks. **Continue** ›
   **Add published application** (older dashboards: *Public hostname*):
   - **Subdomain:** empty. **Domain:** `climpact.app`. **Path:** empty. *Full hostname*
     reads `climpact.app`.
   - **Service URL:** **`http://web:8000`**. The scheme is required, and it is `http`,
     not `https`: Cloudflare serves HTTPS to visitors, and `cloudflared` talks plain HTTP to
     `web` on the Droplet's internal network.
   - *Additional application settings:* leave the defaults (no Host header override).
   - **Add route**.
   If the page was closed, the same form is under **Networks › Tunnels › climpact ›
   Published application routes › Add**. The second route, for the deploy hook, is
   added in [Deploy on release](#deploy-on-release) › D2.
5. Cloudflare normally creates the DNS record itself. If it says *"the DNS record could not
   be created automatically"*, a record for `climpact.app` already exists, usually the
   registrar's parking page carried over when DNS moved to Cloudflare. In the zone's
   **DNS › Records**:
   - Delete the `A`, `AAAA` or `CNAME` records named `climpact.app`, and a `www` record
     that points at a parking page (`www` gets its redirect in #124). Keep `MX` and `TXT`
     records: they are e-mail, not the website.
   - **Add record:** type **CNAME**, name **`@`**, target
     **`<tunnel-id>.cfargotunnel.com`**, proxy status **Proxied** (orange cloud).

   **No DNS record may point at the Droplet's IP.** A record like that would publish the
   origin's address.

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

`CLIMPACT_IMAGE` still reads `...:X.Y.Z` at this point. Step 6 sets it.
`DEPLOY_WEBHOOK_SECRET` is left empty for now (it shows as `MISSING`): it is set in
[Deploy on release](#deploy-on-release) › D1. The other settings
in `.env` (allowed host, upload limit, retention) have the right defaults for
`climpact.app`, and each one is described in the file.

## 6. Start the stack: after the release is published (about 5 min)

Use the latest release from <https://github.com/geoffwalmsley/climpactpy/releases> (its
*Release* workflow must have finished, because that is what pushes the image), written
without the `v`:

```sh
/opt/climpact/update.sh 0.1.2
cd /opt/climpact && docker compose ps   # db, web, worker, purge, deploy-hook, cloudflared up
```

`update.sh X.Y.Z` is the one way to put a release on the Droplet. It fetches
`compose.yaml`, `.env.example`, `deploy-hook.py` and `update.sh` itself from the release's
git tag, pulls `ghcr.io/geoffwalmsley/climpact-web:X.Y.Z`, pins `CLIMPACT_IMAGE` to it in
`.env`, runs the migrations, starts the stack and waits until `/healthz` reports `X.Y.Z`.
The Compose file and the image therefore always come from the same release. Don't edit the
`CLIMPACT_IMAGE` line by hand, and don't use `latest`: the site should change only when a
release is deployed. On the very first deploy a failure leaves the stack as it is (there is
nothing to roll back to); read the messages and `docker compose logs web`.

If the pull fails with *denied* or *unauthorized*, the package may still be private (a
package created by a workflow can start private): on GitHub open the profile's
**Packages › climpact-web › Package settings › Change visibility › Public**, once.

In Cloudflare the tunnel should now show as connected (**Healthy**). Go back to step 4.4
to add the route and its DNS record.

## 7. Smoke test (about 5 min)

From your computer:

```sh
curl -sS https://climpact.app/healthz
# {"status": "ok", "database": "ok", "version": "0.1.2", ...}: the release's version
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

## Cloudflare edge settings

The site has no user accounts, so anyone can upload files and start CPU-heavy jobs on a
1-vCPU Droplet. Cloudflare's free plan is the first line of defence (#124); the app's own
limits and Turnstile are the second (#125). Everything here is set in the Cloudflare
dashboard for the `climpact.app` zone, and nothing in it touches the Droplet except step E2.
Budget **about 30 minutes**. The menu names are those of Cloudflare's dashboard and
documentation in November 2026. Cloudflare renames screens from time to time, so search
the dashboard (⌘K) for the setting's name if a menu has moved.

**Rule expressions are in files.** Each rule below takes its expression from a file in
`deploy/cloudflare/`, so there is nothing to retype. In the rule form, click **Edit
expression** (under the field/operator/value builder), clear the box, and paste the file's
contents: the expression itself, not the file's name. Typing the file name into the
builder's *Value* box makes a rule that matches only that literal path, which never happens. Copy from the file's *Raw* view on GitHub, or with
`pbcopy < deploy/cloudflare/<file>.txt`. A test checks the expressions against every URL
the app serves (`packages/climpact-web/tests/test_deploy_files.py`). If the app gains a URL
that starts a job, add it to `rate-limit.txt` and paste the expression again.

What the free plan allows, and what this uses: 5 WAF custom rules (4 used), 1 rate
limiting rule (1), 10 cache rules (2), 10 redirect rules (1).

### E1. HTTPS and TLS (2 min)

**SSL/TLS › Overview:** the encryption mode must not be *Off* (otherwise the options below
are hidden). Leave it as it is. The tunnel carries the traffic to the Droplet, so the mode
doesn't change anything there.

**SSL/TLS › Edge Certificates:**

- **Always Use HTTPS:** On.
- **Minimum TLS Version:** **TLS 1.2**. Not 1.3: some older systems that the app's users
  may have still lack TLS 1.3.
- **TLS 1.3:** On (the default).
- **HTTP Strict Transport Security (HSTS):** leave it **off**. The app sends the header
  itself (E2), and two headers would conflict.

The universal edge certificate covers `climpact.app` and `*.climpact.app`, so `www` needs
no certificate of its own.

### E2. HSTS from the app (2 min, on the Droplet)

`climpact.app` is HTTPS-only anyway, because the whole `.app` TLD is on the browsers' HSTS
preload list. The app also sends `Strict-Transport-Security: max-age=31536000;
includeSubDomains`, for browsers without the preload list. `.env.example` sets
`CLIMPACT_WEB_HSTS_SECONDS=31536000`. But `climpact-init-env` never changes a value that
is already set, so a `.env` made before #124 still holds `0`. Next time SSH is open (step 2's
temporary rule), as `deploy`:

```sh
cd /opt/climpact
sed -i 's/^CLIMPACT_WEB_HSTS_SECONDS=.*/CLIMPACT_WEB_HSTS_SECONDS=31536000/' .env
grep HSTS .env                 # CLIMPACT_WEB_HSTS_SECONDS=31536000
docker compose up -d --wait    # recreates web, worker and purge with the new setting
```

Releases up to v0.1.0 send `max-age=31536000` without `includeSubDomains`. The release
after #124 adds it, and also sends `Cache-Control: private` on every answer that doesn't
set its own (see E7).

### E3. Redirect `www.climpact.app` to `https://climpact.app` (5 min)

A redirect rule fires only for a hostname whose traffic goes through Cloudflare, and
`www` has had no DNS record since the parking `CNAME` was deleted (#123). So it needs a
**proxied placeholder record** first. Traffic to it never leaves Cloudflare, because the
rule answers first.

1. **DNS › Records › Add record:** type **AAAA**, name **`www`**, IPv6 address **`100::`**
   (a reserved discard address; Cloudflare's documented placeholder for redirect-only
   hostnames), proxy status **Proxied** (orange cloud), TTL Auto. **Save.** Proxied
   records answer IPv4 and IPv6 clients alike, from Cloudflare's addresses.
2. **Rules › Overview › Create rule › Redirect Rule** (if a template list appears,
   *Redirect from WWW to root* fills in the same values. Check them against these):
   - **Rule name:** `www to apex`.
   - **When incoming requests match:** **Wildcard pattern**.
   - **Request URL:** `http*://www.climpact.app/*`
   - **Target URL:** `https://climpact.app/${2}` (`${1}` is the `s` of `https`, `${2}` the
     path).
   - **Status code:** **301**. **Preserve query string:** on.
   - **Deploy.**

Don't add `www.climpact.app` to `CLIMPACT_WEB_ALLOWED_HOSTS` or to the tunnel. The
request never reaches the app.

### E4. WAF managed rules (1 min)

**Security › Settings**, filter **Web application exploits**. The **Cloudflare Free
Managed Ruleset** must be **On**. Cloudflare normally deploys it on free zones by itself.
If it shows as off, turn it on and keep the default settings. The free plan can't
configure it further.

### E5. WAF custom rules (5 min)

**Security › Security rules › Create rule › Custom rules**, four times:

| Rule name | Edit expression: paste the **contents** of | Action |
| --- | --- | --- |
| `Let the deploy call through` | `deploy/cloudflare/waf-skip-deploy.txt` | **Skip** (see below) |
| `Let the uptime check through` | `deploy/cloudflare/waf-skip-healthz.txt` | **Skip** (as above) |
| `Block scanner paths` | `deploy/cloudflare/waf-block.txt` | **Block** |
| `Challenge admin paths` | `deploy/cloudflare/waf-challenge.txt` | **Managed Challenge** |

**Deploy** each one. The skip rule (#126) matches only `POST /_deploy`, the release
workflow's call to the deploy hook, which comes from a GitHub Actions runner in a cloud
provider's address range and could otherwise be challenged. For its action choose
**Skip**, and tick **All remaining custom rules**, **All rate limiting rules** and **All
managed rules**, and under *More components to skip* (if offered) **Browser Integrity
Check** and **Security Level**. Keep **Log matching requests** on. It must be **first** in
the list of custom rules (drag it to the top, or use *Place at: First*). It lets nothing
else through: the hook still checks the request's signature, and refuses everything else.
The second skip rule (#127) matches only `GET` and `HEAD /healthz`, which DigitalOcean's
Uptime check fetches from its own cloud addresses ([A1](#a1-uptime-check-3-min)); give it
the same *Skip* settings, and put it right after the first, so that a cloud address is
never challenged into a false "site down" alert. `/healthz` reveals nothing but the
version and costs one `SELECT 1`. `waf-block.txt` blocks paths the app never serves: `*.php`, `*.asp`,
`*.aspx`, `*.jsp` and `*.cgi`, WordPress paths (`/wp-*`, `.../wp-admin`, `wp-content`,
`wp-includes`), `/cgi-bin/`, and any path segment starting with a dot (`/.env`,
`/.git/...`), except `/.well-known/`. `waf-challenge.txt` challenges `/admin*` (the app has
no admin site, but scanners look for one) and `/patterns/` (the pattern library, a 404 in
hosted mode unless `CLIMPACT_WEB_PATTERN_LIBRARY` is set). Neither rule matches a page of
the app (tested). Don't add a geo or ASN rule unless the analytics show abuse from one place.

### E6. Rate limiting the job-starting requests (5 min)

**Security › Security rules › Create rule › Rate limiting rules:**

- **Rule name:** `Job-starting requests`.
- **When incoming requests match:** click **Edit expression** and paste the **contents** of
  `deploy/cloudflare/rate-limit.txt` (not its name).
- **With the same characteristics:** **IP** (the only choice on the free plan).
- **When rate exceeds:** **10** requests per **10 seconds**.
- **Then take action:** **Block**, with the default response (HTTP 429).
- **Duration:** **10 seconds**. The free plan offers only 10 s for both the period and
  the duration.
- **Deploy.**

**Why a list of paths, and not "POSTs to `/w/`":** the free plan's rule can match the
**path only, not the method**. Its counter would therefore count every GET under a prefix like
`/w/` (a workspace and its stations, `/w/<id>/<station>/…`). The job pages poll their
progress with htmx once a second (`.../quality/progress`, `.../indices/progress`,
`/jobs/<id>/progress`, `/w/<id>/batch/progress`), and form fields are checked with htmx
POSTs as they change (`.../setup/validate`, `.../settings/validate`,
`/w/<id>/batch/options`). A prefix rule would
block an ordinary visitor within 10 seconds of starting a job. `rate-limit.txt` lists only
the URLs that take an upload or start a job (upload and sample, *load*, *replace file*,
*run quality checks*, *replace file after QC*, *continue*, *recalculate*, *sector*, batch
upload, add files and run, job retry, and gridded upload and sample, which are off in
hosted mode). Their GETs are page loads. A person filling in the forms makes 2–4 of these
requests in 10 seconds, and a script making a burst makes many more. Tune the number from
**Security › Analytics** once there is traffic.

### E7. Caching `/static/` at the edge (5 min)

**Caching › Cache Rules › Create rule**, twice:

| Rule name | Edit expression: paste the **contents** of | Settings |
| --- | --- | --- |
| `Static files` | `deploy/cloudflare/cache-static.txt` | **Cache eligibility:** Eligible for cache. **Edge TTL:** *Use cache-control header if present, use default Cloudflare caching behavior if not*. **Browser TTL:** *Respect origin* |
| `Bypass everything else` | `deploy/cloudflare/cache-bypass.txt` | **Cache eligibility:** Bypass cache |

**Deploy** each one. The two expressions never match the same request, so their order
doesn't matter. Static files have content hashes in their names
(`climpact.36cde401c4f6.css`), and WhiteNoise sends them with `Cache-Control: public,
max-age=315360000, immutable`, so caching them for as long as the origin says is safe. A
new release has new names.

The bypass rule matters because, by default, Cloudflare caches answers by file extension
alone (`.csv`, `.png`, `.pdf`, `.zip`, ...) when the origin sends no `Cache-Control`, and
it ignores cookies when it does. The job downloads (`/jobs/<id>/files/...`) belong to one
visitor's session and must never be cached. The app also marks every such answer
`Cache-Control: private` (from the release after #124), so either one alone is enough.

### E8. Bot Fight Mode (1 min)

**Current state: off** (since the first automatic deploy, 2026-11; recorded on #126). It
challenged the release workflow's call to the deploy hook, and the free plan can't exempt
that call (see [D5](#d5-check-it-5-min-then-one-release)). It would also challenge the
uptime check from DigitalOcean's addresses ([A1](#a1-uptime-check-3-min)), which no rule
can exempt either. Turning it back on needs deploys that don't call in from outside (the
Droplet pulling releases instead), and then a look at whether the uptime check still
passes. The rest of this section describes it for that day.

**Security › Settings**, filter **Bot traffic** › **Bot fight mode:** On or Off.

Bot Fight Mode challenges traffic that Cloudflare scores as automated. It **cannot be
skipped** by a custom rule, so nothing exempts the app's own requests, nor the release
workflow's call to the deploy hook (see [Deploy on release](#deploy-on-release) › D5).
Cloudflare's JavaScript detections (an inline script it adds to every HTML page, which
loads more from `/cdn-cgi/challenge-platform/`) run whether Bot Fight Mode is on or off,
and the app's Content Security Policy allows them by the nonce in its header (#164; see
E9 and `TECHNICAL.md` › Content Security Policy). A real browser that loaded the page and
passed the detections sends the clearance with its htmx requests, so they aren't
challenged.

**What to watch for (htmx):** htmx swaps in only 2xx answers. If the edge ever answers a
poll with a challenge (HTTP 403 and the header `cf-mitigated: challenge`) or a 429, htmx
drops it, so **the progress bar stops moving while the job carries on** on the worker. A
validation POST that is challenged simply shows no inline message. Reloading the page
recovers, because a full page load can solve the challenge. To check:

- In the browser, run a station analysis with the sample data (upload → QC → indices →
  results → downloads) with the developer tools' **Network** tab open, filtered on
  `progress` and `validate`. Every request should be **200**. A 403 or 429 there is the
  edge, not the app.
- **Security › Analytics › Events** for the first days: look for events on `/station/`,
  `/batch/` or `/jobs/` paths from real visitors (service *Bot fight mode*, *Rate limiting
  rules* or *Custom rules*).

If Bot Fight Mode challenges real visitors' htmx requests, turn it **off**. It has no
exceptions on the free plan, and the rate limit plus Turnstile (#125) still guard the jobs.
Record the decision in #124.

### E9. Turnstile widget and keys (5 min)

Turnstile is set per account, not per zone. Go to the account home, then **Turnstile ›
Add widget**:

- **Widget name:** `climpact`.
- **Hostname management:** add **`climpact.app`** (pick it from the account's zones).
- **Widget mode:** **Managed**.
- **Pre-clearance support:** **No**.
- **Create.**

The page then shows the **site key** and the **secret key**. Store both in the password
manager (one item, `climpact.app Turnstile`). Never put them in the repository or an
issue. The keys can be shown again later under the widget's settings, and the secret can
be rotated there.

**Put them in `.env`** (from the release with #125; earlier images ignore them). Open SSH as
in step 2, then `nano /opt/climpact/.env` and set both lines (add them if the file predates
#125; `.env.example` has them with a comment):

```sh
CLIMPACT_WEB_TURNSTILE_SITE_KEY=<site key>
CLIMPACT_WEB_TURNSTILE_SECRET_KEY=<secret key>
```

then `cd /opt/climpact && docker compose up -d --wait` and close SSH. Set both or neither:
with one alone the app refuses to start. Empty, Turnstile is off and the forms work as
before. To check: open **https://climpact.app/station/** in a browser. A small Cloudflare
box appears above **Load the file**; it usually ticks itself without asking anything. Run
the sample station through to the results (each step that starts a calculation shows the
box). A **Not accepted** page saying the check failed means the keys don't match the
widget, or the hostname isn't on the widget's list.

The app checks each token with Cloudflare (`challenges.cloudflare.com`), so `web` is the
one service with a route out (the `egress` network in `compose.yaml`). The app's Content
Security Policy (#137) allows Cloudflare's script and frame from
`https://challenges.cloudflare.com` when both keys are set, and nothing from Cloudflare
otherwise.

**Content Security Policy.** The policy is enforced by default. To watch it before it
blocks anything (after the first release that has it, or after a change to the pages),
set `CLIMPACT_WEB_CSP_REPORT_ONLY=true` in `.env` (a `.env` made before #137 has no such
line: add it) and `docker compose up -d --wait`. In a browser, open the pages with the
developer tools' console showing and run the sample station through to the results: any
line mentioning "Content Security Policy" is a violation to report in an issue. Then set
it back to `false` and run `docker compose up -d --wait` again. `curl -sI
https://climpact.app/ | grep -i content-security` shows which header is sent. The one
expected message is `Fetch API cannot load data:,` from inside Turnstile's own frame (its
URL ends `flexible?lang=en`), which the app's policy doesn't govern. The scripts
Cloudflare adds to each page are allowed (#164): JavaScript detections by the nonce in the
header, Web Analytics by `CLIMPACT_WEB_CF_WEB_ANALYTICS=true` (the default; set `false` if
the zone's Web Analytics is turned off).

### E10. Check it (5 min)

From your computer, in a checkout of the repository:

```sh
bash deploy/check-edge.sh            # everything except the rate limit
bash deploy/check-edge.sh --burst    # also fires 25 POSTs at /jobs/<made-up id>/retry
```

The burst's POSTs carry no CSRF token, so the app refuses each one (403) before doing
anything. No job starts, and the rate limit blocks your IP address on the job-starting
paths only, for 10 seconds. Once everything is applied, every line reads `PASS`:

```
PASS  TLS 1.2 accepted
PASS  TLS 1.1 refused (also passes if your curl cannot speak TLS 1.1)
PASS  http:// -> https://climpact.app/station/?x=1
PASS  https://www.climpact.app/help/?x=1 -> 301 https://climpact.app/help/?x=1
PASS  http://www.climpact.app/help/?x=1 ends at 200 https://climpact.app/help/?x=1
PASS  HSTS: max-age=31536000; includeSubDomains
PASS  home page 200, not challenged
PASS  second request for /static/climpact_web/css/climpact.<hash>.css: cf-cache-status: HIT
PASS  / not cached at the edge (cf-cache-status: DYNAMIC; cache-control: private)
PASS  /station/sample.txt not cached at the edge (cf-cache-status: DYNAMIC; cache-control: private)
PASS  /wp-login.php blocked (403)
PASS  /.env blocked (403)
PASS  /.git/config blocked (403)
PASS  /cgi-bin/test blocked (403)
PASS  /.well-known/ not blocked (404 from the app)
PASS  /admin/ challenged (cf-mitigated: challenge)
PASS  GET /station/ 200
PASS  GET /batch/ 200
PASS  GET /help/ 200
PASS  GET /jobs/ 200
PASS  htmx-style poll reaches the app (404 for a made-up job)
PASS  /healthz 200, ok, not cached (cf-cache-status: DYNAMIC; cache-control: max-age=0, no-cache, no-store, must-revalidate, private)
      25 POSTs to /jobs/<id>/retry: 403 403 403 403 403 403 403 403 403 403 429 429 429 429 429 429 429 429 429 429 429 429 429 429 429
PASS  burst blocked by the rate limit (429 after about 10 requests)
      waiting 12 s for the block to end...
PASS  after the block: 403 from the app again (no CSRF token)

All checks passed.
```

Until the release after #124 is deployed, the HSTS line is a `NOTE` (no
`includeSubDomains`) and `cache-control` reads `none`. Both are fine. The cache status may
read `BYPASS` instead of `DYNAMIC`. Anything but `HIT` passes. The burst should give about ten
403s (from the app), then 429s (from Cloudflare). Cloudflare updates its counters
asynchronously, so the first 429 can come anywhere from the 11th request to about the
15th. That is why the script sends 25, one after another: a burst sent all at once can
slip through before the counter catches up. If **all** 15 are 403, the rule
isn't matching. Check that it is deployed, wait a minute after deploying for it to reach
every data centre, and run the script again.

If **every** check that fetches a page fails with `cf-mitigated: challenge`, Bot Fight
Mode (if it is on) is classing `curl` from your network as a bot. That is not what browsers see: check
the pages in a browser instead (E8), and run the script from another network if you want a
clean run. Then do the browser walk-through of E8 and record the date and the results in
#124.

## Deploy on release

Publishing a **final** GitHub Release deploys it to climpact.app by itself (#126). A merge
to `main` or a pre-release deploys nothing. The release workflow's last job, `deploy`,
sends a signed request to `https://climpact.app/_deploy`. The tunnel passes it to the
`deploy-hook` service, which checks the signature and leaves the version in
`/opt/climpact/hook/request`. A systemd unit on the Droplet (`climpact-deploy.path`) sees
the file and runs `/opt/climpact/update.sh X.Y.Z` as `deploy`, one deploy at a time:

1. fetch the release's `compose.yaml`, `.env.example`, `deploy-hook.py` and `update.sh`,
   and pull its image (if this fails, nothing has changed);
2. run the migrations, then `docker compose up -d --wait`;
3. ask `/healthz` inside the `web` container until it reports `X.Y.Z` (3 minutes at most);
4. if 2 or 3 fails, put the previous release back and log **ROLLED BACK**;
5. remove old app images (the new and the previous one are kept).

Meanwhile the `deploy` job polls `https://climpact.app/healthz` and goes green only once
it reports the new version (10 minutes at most). A rolled-back deploy fails the job. The
Droplet still accepts **no inbound connections**: the request comes through the tunnel.
Design and details: `TECHNICAL.md` › Deployment › Deploy on release.

Set it up once, in this order (about 20 minutes). D1–D3 are in GitHub and Cloudflare; D4
needs SSH (step 2's temporary rule).

### D1. The secret, on both sides (5 min)

The request is signed with a shared secret, `DEPLOY_WEBHOOK_SECRET`. Make it on your own
computer, and never put it in the repository, an issue or a chat:

```sh
openssl rand -hex 32        # copy the output; it is the secret
```

1. **GitHub › the repository › Settings › Environments › New environment**: name
   **`production`**. Under *Deployment branches and tags* choose **Selected branches and
   tags** › *Add deployment branch or tag rule* › **Ref type: Tag**, pattern **`v*`**.
   No reviewers (the job should run unattended). Under **Environment secrets › Add
   environment secret**: name `DEPLOY_WEBHOOK_SECRET`, value the secret. Save.
   The tag rule means only a run for a release tag can use the environment and read the
   secret.
2. **On the Droplet** (in D4): `nano /opt/climpact/.env` and set
   `DEPLOY_WEBHOOK_SECRET=<the secret>` (add the line if the file predates #126).

Keep it in the password manager too (one item, `climpact.app deploy hook`). To rotate it,
see [Operating the server](#operating-the-server) › *Rotate a secret*.

### D2. The tunnel route for `/_deploy` (3 min)

**Zero Trust › Networks › Tunnels › climpact › Published application routes › Add**:

- **Subdomain:** empty. **Domain:** `climpact.app`. **Path:** **`_deploy`**.
- **Service URL:** **`http://deploy-hook:9000`**.
- **Add route** (or *Save*).

Routes are matched **top to bottom**, so the new one must be **above** the existing
`climpact.app` route without a path (`http://web:8000`), or the request goes to the app.
If it was added below, drag it up; if the dashboard can't reorder, delete the catch-all
route and add it again (same values as step 4.4), so that it comes last. The path is a
regular expression matched anywhere in the path; the app has no other path containing
`_deploy`, and the hook answers 404 to anything but exactly `/_deploy`. No new DNS record
is needed.

### D3. The Cloudflare skip rule (3 min)

Add the custom rule **`Let the deploy call through`** from E5
(`deploy/cloudflare/waf-skip-deploy.txt`, action **Skip**, first in the list). No other
rule needs changing: none of the block, challenge, rate-limit or cache rules matches
`POST /_deploy` (tested), and the *Bypass everything else* cache rule plus the hook's
`Cache-Control: no-store` keep it out of the cache.

### D4. On the Droplet: the hook and its watcher (5 min)

A Droplet created from this `cloud-init.yaml` already has `update.sh`, the drop folder and
the systemd units; skip to the `.env` line. The Droplet made before #126 needs them once.
Open SSH (step 2's rule), then as `deploy`:

```sh
cd /opt/climpact
curl -fsSL https://raw.githubusercontent.com/geoffwalmsley/climpactpy/main/deploy/update.sh -o update.sh
chmod 0755 update.sh
sudo ./update.sh --install-hook     # hook/ and climpact-deploy.path; prints "installed"
sudo rm -f /usr/local/bin/climpact-use   # replaced by update.sh
nano .env                           # DEPLOY_WEBHOOK_SECRET=<the secret from D1>
./update.sh --fetch main            # main's compose.yaml, with the deploy-hook service
docker compose up -d --wait         # starts deploy-hook; the app keeps its image
docker compose ps                   # deploy-hook up
systemctl status climpact-deploy.path   # active (waiting)
```

`--fetch main` changes only the Compose files (the next release replaces them with its
own); `CLIMPACT_IMAGE` stays as it is. Close SSH again.

### D5. Check it (5 min, then one release)

From your own computer, a request without a valid signature must be refused **by the
hook** (the JSON says `"hook": "climpact-deploy"`) and change nothing:

```sh
curl -sS -i -X POST https://climpact.app/_deploy -d '{"version": "0.0.0"}' | sed -n '1p;$p'
# HTTP/2 401
# {"hook": "climpact-deploy", "status": "bad signature"}
curl -sS -o /dev/null -w '%{http_code}\n' https://climpact.app/_deploy    # 405
bash deploy/check-edge.sh            # still all PASS
```

| You get | Meaning |
| --- | --- |
| 401 with `"hook": "climpact-deploy"` | Right. |
| 503 with `"hook": "climpact-deploy"` | The hook has no secret: D1 step 2, then `docker compose up -d deploy-hook`. |
| 404 (the app's HTML page), or any answer without `"hook"` | The request reached the app: the route (D2) is missing or below the catch-all. |
| 502 or 530 from Cloudflare | The route exists but `deploy-hook` isn't running: `docker compose ps`, `docker compose logs deploy-hook`. |
| 403 with header `cf-mitigated: challenge` | Cloudflare challenged it from your network (see below). |

Then **publish a patch release** (`RELEASING.md`). After `publish`, the `deploy` job runs:
*Ask the Droplet to deploy* should print `HTTP 202`, and *Wait for climpact.app to report
the version* should end with `climpact.app runs X.Y.Z`. To watch the Droplet side, open
SSH and run `journalctl -u climpact-deploy -f`.

**If the job says Cloudflare challenged the request:** Bot Fight Mode (E8) is classing
`curl` from GitHub's runners as a bot. It can't be exempted on the free plan, so turn it
**off** (**Security › Settings › Bot traffic › Bot fight mode**), record that in #126, and
**re-run** the `deploy` job. The signature, the rate limit and Turnstile still protect the
site. This happened on the first release, and Bot Fight Mode has been off since (E8).

### Deploying and rolling back by hand

- **Again, or after fixing something:** in GitHub Actions, open the release's *Release*
  run and **Re-run** the `deploy` job. It deploys the same version again.
- **A specific version** (also to roll back): open SSH, `/opt/climpact/update.sh X.Y.Z`.
  It prints each step and ends with `deployed X.Y.Z` or **ROLLED BACK**. Releases 0.1.1
  and older lack the deploy hook: rolling back to one keeps the current `deploy-hook.py`
  and `update.sh`, but its `compose.yaml` has no `deploy-hook` service, so the next
  release must then be deployed by hand.
- **Migrations are not undone** by a rollback. A release whose migrations the previous
  release can't work with says so in its notes, and rolling it back then needs a database
  restore.

**When a deploy fails** (the `deploy` job is red):

| The job says | Look at |
| --- | --- |
| *refused the signature* | The two copies of `DEPLOY_WEBHOOK_SECRET` (D1) differ, or the Droplet's clock is off by over 5 minutes (`timedatectl`). |
| *not from the deploy hook* / *the tunnel could not reach* | D2 and `docker compose ps` (D5's table). |
| *still reports X after 600 s* | The Droplet rolled back or is still working: `journalctl -u climpact-deploy`, `tail -n 50 /opt/climpact/deploy.log`, `docker compose logs --tail 100 web`. **ROLLED BACK** means the old release is serving again. |

Each deploy's steps go to the journal (`journalctl -u climpact-deploy` for the hook's
deploys, `journalctl -t climpact-deploy` for those run by hand) and one line each to
`/opt/climpact/deploy.log`.

## Running it

**Update to a new release:** publish it. The release workflow deploys every final
release by itself (see [Deploy on release](#deploy-on-release)). To deploy or roll back by
hand, re-run the release's `deploy` job in GitHub Actions, or open SSH as in step 2 and
run `/opt/climpact/update.sh X.Y.Z` (an earlier version to roll back; release images stay
on ghcr.io), then close SSH. A database migration that the previous release can't work
with will say so in the release notes.

**Get a shell when the firewall is closed** (break glass):
- Usual way: add the temporary SSH rule for your IP (step 2), then `ssh deploy@<ip>`.
- DigitalOcean's **Droplet Console** (in the browser) also connects over SSH, but from
  DigitalOcean's own addresses, which are not published, so it works only while port 22
  is open to everyone. Log in as `deploy`. Prefer the rule for your own IP.
- If SSH itself is broken: **Access › Reset root password** (DigitalOcean emails a
  password), then the **Recovery Console**, which is the Droplet's screen and keyboard and
  needs no network. Root can log in there, though not over SSH.

**Logs** (in `/opt/climpact`; rotated at 10 MB × 3 per container): `docker compose logs -f web worker` for the app and its jobs; `docker compose logs
cloudflared` for the tunnel's connection; `docker compose logs deploy-hook` for deploy
requests (the deploys themselves: `journalctl -u climpact-deploy` and `deploy.log`, see
[Deploying and rolling back by hand](#deploying-and-rolling-back-by-hand)); `db` and
`purge` likewise.

**Abuse limits** (#125; the settings are in `.env`, each described there): besides
Turnstile (E9), the app refuses a new job when the visitor (by IP address) already has 2
waiting or running, or has started 30 in 24 hours; it refuses new jobs for everyone while
more than 20 wait or while the disk has less than 2 GB free ("busy, try later", so nothing
fails halfway); and the worker stops a job that runs longer than 60 minutes. Every
refusal is logged by `web` with the address and the reason:

```sh
docker compose logs web | grep Refused
# Refused POST /station/<id>/load from 203.0.113.7: active-quota:2
```

The reasons are `turnstile-missing`, `turnstile-failed:<Cloudflare's codes>`,
`turnstile-unavailable` (Cloudflare didn't answer), `active-quota:<n>`,
`daily-quota:<n>`, `queue-full:<n>` and `disk-low:<free MB>`. Many refusals from one
address point to a script, so block it, or lower the rate limit (E6). Real visitors hitting
`active-quota` or `daily-quota` mean the limit is too tight, so raise it in `.env` and run
`docker compose up -d`. `disk-low` needs space: check `df -h /` and the size of the media
volume (`docker system df -v`). The worker logs `stopped at the time limit` for a job it
stopped.
Bootstrap log: `/var/log/cloud-init-output.log`. DigitalOcean's Monitoring graphs CPU,
memory and disk, and mails when they run high (see [Alerts](#alerts)).

**Automatic updates:** Ubuntu's security updates and Docker's packages install every day
(`unattended-upgrades`). When an update needs a reboot, the Droplet reboots at 03:30 UTC,
and the stack comes back by itself (`restart: unless-stopped`). Docker's `live-restore`
keeps the containers running while Docker itself is upgraded. A weekly timer
(`climpact-image-prune.timer`) deletes images no container has used for 30 days. Expired
jobs are purged by the stack itself (the worker every hour, the `purge` service daily).
Nothing updates the app except a release (see [Deploy on release](#deploy-on-release)).

**Rotating secrets, resizing, rebuilding:** see [Operating the server](#operating-the-server).

## Alerts

Four things should reach the owner by e-mail without anyone looking (#127): the site is
down, the Droplet is running out of memory or disk, the bill moves, and a deploy failed.
The resource and billing alerts are free. The ticket assumed Uptime's free allowance
covers the one check this needs; the create form shows a price if it doesn't. They are
all set in the DigitalOcean control panel, not on the Droplet. Budget **about 15 minutes**.
The menu names are DigitalOcean's in November 2026; search the control panel if one has
moved. Alerts go to the e-mail address of the DigitalOcean account (or the team members
you pick in each form).

### A1. Uptime check (3 min)

**Monitoring › Uptime › Create Uptime Check** (or the Droplet's page › *Uptime*):

- **Type:** **HTTPS**. **URL:** **`https://climpact.app/healthz`**.
- **Regions:** two or three, for example *US West*, *US East* and *Europe*, so the check
  doesn't depend on one network path.
- **Name:** `climpact.app healthz`. **Project:** `climpact`.
- **Alerts:** add three:
  - **Downtime:** e-mail, after **5 minutes** down (or the nearest the form offers).
    Shorter would mail on the planned blips: the 03:30 UTC reboot after a security update
    takes a minute or two, and a deploy recreates `web` in seconds.
  - **Latency:** above **5000 ms** for **10 minutes**: the site is up but so slow that
    the edge or the Droplet is struggling.
  - **SSL certificate expiry:** **7 days** before. Cloudflare renews the edge certificate
    itself, so this mails only if that renewal fails.
- **Create.**

`/healthz` answers 200 with `"status": "ok"` when the app and its database answer, 503
when the database doesn't, and Cloudflare answers 502 or 530 when `web` or the tunnel is
down, so each of these reads as down. It goes through Cloudflare like any visitor, so it
also catches a broken tunnel or edge setting. Nothing at the edge gets in the way: no
block, challenge or rate-limit rule matches `/healthz`, the skip rule
`Let the uptime check through` (E5) keeps the managed rules and Browser Integrity Check
off it, the cache rules bypass it, and the app sends it `Cache-Control: no-store`
(tested by `test_deploy_files.py`; `check-edge.sh` checks it live). If Bot Fight Mode is
ever turned back on (E8), check that the uptime check still passes: no rule can exempt it
from Bot Fight Mode.

**Test it once** (the acceptance check of #127). Open SSH (step 2), then as `deploy`:

```sh
cd /opt/climpact && docker compose stop web
```

Within about 5–7 minutes a *down* e-mail arrives (the site answers 502 meanwhile). Then:

```sh
docker compose up -d --wait     # web back; an "up" e-mail follows
```

Close SSH, and record the date and how long the e-mail took in #127.

### A2. Droplet resource alerts (5 min)

They need DigitalOcean's metrics agent, which **Monitoring** at creation installs (step
1). Check: the Droplet's **Graphs** page shows *Memory* and *Disk* graphs. If it offers to
install the agent instead, open SSH and run DigitalOcean's documented installer,
`curl -sSL https://repos.insights.digitalocean.com/install.sh | sudo bash`.

**Monitoring › Resource Alerts › Create Resource Alert** (older control panels: *Alert
Policies*), three times:

| Metric | Rule | Why this value |
| --- | --- | --- |
| **Memory Utilization** | above **90 %** for **10 min** | The containers' limits add up to more than 2 GB (swap covers the peaks). Lasting 90 % means a stuck job or a leak, not one job's peak |
| **Disk Utilization** | above **80 %** for **5 min** | 80 % of 50 GB leaves 10 GB. The app refuses new uploads below 2 GB free (`disk-low`), so this mails well before visitors notice |
| **CPU Utilization** | above **90 %** for **30 min** | Any job keeps the one CPU near 100 % while it runs, often for 10 minutes or more, so 15 minutes (the ticket's figure) would mail on ordinary use. 30 minutes means a queue of jobs or a runaway one |

For each: **Apply to** the tag **`climpact`** (not the Droplet's name), so a Droplet
created again later is covered from its first boot. **Notify** by e-mail. **Create**.

**When one fires:** open SSH, `cd /opt/climpact`, then:
- memory or CPU: `docker stats --no-stream` (which container), `docker compose logs --tail
  100 worker` (which job), `docker compose logs web | grep Refused | tail` (someone
  scripting the site; see *Abuse limits* in [Running it](#running-it)). The worker stops a
  job after 60 minutes by itself.
- disk: `df -h /`, `docker system df -v` (the `media` and `pgdata` volumes, images).
  Expired jobs are purged daily and logs are rotated, so steady growth means something
  else is writing. If it is genuine use, [resize](#resize-the-droplet) the disk.

### A3. Billing alert (1 min)

Account menu (top right) › **Billing** › **Billing alerts** › **Set alert** (or *Edit*):
**$15**, **Save**. DigitalOcean e-mails once the month's usage passes it.

The expected bill is **$12/mo**: the Droplet, with Monitoring, the Cloud Firewall and the
first 2 TB of traffic included, plus Uptime if the one check is not free. No backups, snapshots, registry, volumes or load
balancer. Anything above $12 is something new. Raise the alert by the difference after a
[resize](#resize-the-droplet). The domain is paid to its registrar, not DigitalOcean.

### A4. Deploy failures and the tunnel (2 min, optional)

- **GitHub** mails the person who published a release when its `deploy` job fails, if
  **your profile › Settings › Notifications › Actions** has e-mail on (the default; *Only
  notify for failed workflows* is enough). A failed deploy has rolled back or changed
  nothing, so the site stays up (see [Deploy on release](#deploy-on-release)).
- **Cloudflare** can mail when the tunnel is down: **Notifications › Add › Tunnel Health
  Alert** (if the free plan offers it), for the tunnel `climpact`. A1 already catches this;
  the Cloudflare mail says *why* the site is down.

## Backups

**Decision (#127): no DigitalOcean Backups or Snapshots, and no scheduled database dump.**
A lost or broken Droplet is created again from this runbook (see
[Rebuild from nothing](#rebuild-from-nothing-and-restore)), which takes under an hour.

What the Droplet holds, and why none of it needs keeping:

| Data | Where | If it is lost |
| --- | --- | --- |
| Jobs: queue, status, settings | Postgres (`pgdata` volume) | Visitors start again. Every job expires after 7 days, and each one is visible only to the browser session that made it; there are no accounts |
| Uploads and results | the `media` volume | The same: expire with their job |
| Secrets | `/opt/climpact/.env` | Made again or fetched again (see [Credentials](#credentials)) |
| Code, Compose files, images | the release's git tag, ghcr.io | Fetched by `update.sh` |

A dump kept on the Droplet would not survive the loss it is meant for. One kept elsewhere
would need off-Droplet storage, which costs money and adds a credential, to protect data
that expires within a week. And a dump without the `media` volume restores jobs whose files
are gone. Revisit this if the app ever keeps something beyond the 7 days or gains accounts.

**A dump by hand, before a risky release.** Migrations are not undone by a rollback
([Deploying and rolling back by hand](#deploying-and-rolling-back-by-hand)). Before
deploying a release whose notes warn about its migrations, open SSH and, as `deploy`:

```sh
cd /opt/climpact
docker compose exec -T db pg_dump -U climpact -Fc climpact > ~/climpact-$(date -u +%F).dump
```

To restore it after rolling the code back (`update.sh X.Y.Z` of the old release):

```sh
docker compose stop web worker purge
docker compose exec -T db pg_restore -U climpact -d climpact --clean --if-exists < ~/climpact-YYYY-MM-DD.dump
docker compose up -d --wait
```

Delete the file once the release has settled (`rm ~/climpact-*.dump`).

## Credentials

Every secret the service uses, where it lives and how to change it. Nothing in the
repository, the user data, an issue or the GitHub Actions logs is secret. **Password
manager** means the owner's (1Password), one item each, named as below.

| Credential | Allows | Lives in | Expires | Rotate |
| --- | --- | --- | --- | --- |
| `CLIMPACT_WEB_SECRET_KEY` | signing sessions and CSRF tokens | `.env` only (made by `climpact-init-env`) | never | [below](#rotate-a-secret) |
| `POSTGRES_PASSWORD` | the database, reachable only on the stack's internal network | `.env` only, and inside the `pgdata` volume, which keeps the password it was created with | never | [below](#rotate-a-secret): inside Postgres first |
| `TUNNEL_TOKEN` | running a connector for the tunnel, i.e. serving climpact.app | `.env`; Cloudflare shows it again (**Zero Trust › Networks › Tunnels › climpact › Configure**, the Docker command) | never | **Refresh token** |
| Turnstile site key | nothing: it is public, in every form page | `.env`, the widget's settings | never | only with a new widget |
| Turnstile secret key | checking the widget's tokens | `.env`, the widget's settings, password manager `climpact.app Turnstile` | never | **Rotate secret key** |
| `DEPLOY_WEBHOOK_SECRET` | asking the Droplet to deploy a published release (no other command) | GitHub environment `production` (write-only: GitHub never shows it again), `.env`, password manager `climpact.app deploy hook` | never | [below](#rotate-a-secret) |
| SSH key for `deploy` | a shell with sudo on the Droplet, only while the firewall's SSH rule is open | private half: the owner's 1Password SSH agent. Public half: `/home/deploy/.ssh/authorized_keys`, and **DigitalOcean › Settings › Security › SSH keys** for new Droplets | never | [below](#rotate-a-secret) |
| root password | the Recovery Console only (SSH refuses root) | none is set; **Access › Reset root password** mails a one-time one | after use | lock it again after use: `sudo passwd -l root` |
| `GITHUB_TOKEN` (release workflow) | pushing the image (`packages: write`, the `publish` job only); reading the repository elsewhere | made by GitHub for each job | at the end of the job | nothing to rotate |
| PyPI and TestPyPI publishing | uploading `climpact` and `climpact-web` | nothing stored: Trusted Publishing (OIDC) from `release.yml` in the environments `pypi` (needs the maintainer's approval) and `testpypi` | minutes | nothing to rotate; to revoke, remove the publisher in the project's PyPI settings |

**No other tokens exist.** The image is a public package on ghcr.io, so the Droplet pulls
without a login, and there is no DigitalOcean registry. Nothing uses a DigitalOcean or
Cloudflare API token: every setting is made by hand in the dashboards. Cloudflare Web
Analytics needs none either: its beacon token is public, in every page, and the app only
allows the beacon's script (`CLIMPACT_WEB_CF_WEB_ANALYTICS`, E9). If one is ever
made (for `doctl`, Terraform or an AI assistant's MCP server), give it the narrowest scope
and an expiry date, and add it to this table.

**Account logins**, each with two-factor authentication (an authenticator app or a
passkey) and its recovery codes in the password manager: DigitalOcean, Cloudflare,
GitHub (the repository, the `production` environment and the ghcr.io package), PyPI and
TestPyPI, and the registrar of `climpact.app`. At a handover these accounts are not
shared: the new owner uses their own (see [Moving it to other accounts](#moving-it-to-other-accounts-handover)).

## Operating the server

All of these except the GitHub-only steps need SSH: open the temporary rule for your IP
(step 2), and delete it again afterwards (step 8).

### Rotate a secret

Rotate one when it may have leaked, when someone who had it no longer should, and at a
handover. Each change to `.env` takes effect with `cd /opt/climpact && docker compose up -d
--wait`, which recreates only the services whose settings changed.

- **Tunnel token:** **Zero Trust › Networks › Tunnels › climpact › Refresh token** (or
  create a new tunnel). Put the new token in `.env` (`nano /opt/climpact/.env`), then
  `docker compose up -d --wait`. The site is unreachable for the seconds `cloudflared`
  takes to reconnect.
- **Turnstile secret key:** account home › **Turnstile ›** the widget **› Settings ›
  Rotate secret key**. Put the new one in `.env`, `docker compose up -d --wait`, and
  update the password manager. The site key stays.
- **Django secret key:** make one with
  `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`, replace it in `.env`,
  `docker compose up -d --wait`. Every visitor's session ends, and with it **access to
  their open jobs** (a job belongs to the session that made it): do it at a quiet time.
- **Deploy hook secret:** make a new one (`openssl rand -hex 32`), set it in GitHub (D1:
  **Settings › Environments › production › DEPLOY_WEBHOOK_SECRET › Update**) and in
  `.env`, then `docker compose up -d deploy-hook`, and update the password manager. Until
  both match, deploys fail with *refused the signature* and nothing else changes.
- **Postgres password:** the database keeps the password it was created with, so changing
  `.env` alone breaks the app. Make one with `openssl rand -hex 32` (it goes into a URL,
  so keep it hex), change it inside Postgres first
  (`docker compose exec db psql -U climpact -c "ALTER USER climpact PASSWORD '<new>'"`),
  then in `.env`, then `docker compose up -d --wait`.
- **SSH key:** make a new key in 1Password. Add its public half as a new line in
  `/home/deploy/.ssh/authorized_keys`, check in a second terminal that it logs in, then
  delete the old line. Replace the key in **DigitalOcean › Settings › Security › SSH
  keys** too, so new Droplets get it.

### Resize the Droplet

When the memory alert (A2) keeps firing, or the queue is often full (`queue-full` in the
`Refused` lines). The stack runs one job at a time (one `worker`), and its containers'
memory limits are set in `compose.yaml`, so more RAM gives the system headroom (less swap,
more cache) but does not let a single job use more; a second CPU keeps the pages quick
while a job runs. Running jobs side by side, or raising a limit, is a change to
`compose.yaml` in a release.

1. Expect a few minutes' downtime, and the A1 e-mail if it lasts over 5 minutes.
2. The Droplet's page › **Power** › **Turn off** (a clean shutdown; a running job is
   handed back to the queue and runs again after).
3. **Resize** › **CPU and RAM only**, then the new size (for example Basic Regular,
   4 GB / 2 CPUs). Not *Disk, CPU and RAM*: a bigger disk can never be made smaller again,
   and 50 GB is plenty unless the disk alert says otherwise. **Resize**.
4. **Power on**. The stack starts by itself (`restart: unless-stopped`). Check
   `curl -sS https://climpact.app/healthz`.
5. Raise the billing alert (A3) by the price difference, and update the size in
   `TECHNICAL.md` › Deployment if the change is meant to stay.

Going back down works the same way, as long as the disk was not resized.

### Rebuild from nothing (and restore)

When the Droplet is lost, broken beyond repair, or should be moved to another region.
Budget **under an hour**. **Nothing is restored, and only jobs are lost**: every job
expires within 7 days anyway, and visitors start theirs again (see [Backups](#backups)).
What stays outside the Droplet and needs no change: the Cloud Firewall (it applies by the
tag `climpact`), the A1 uptime check (it checks the URL), the A2 alerts (by tag), the
tunnel and its two routes, the DNS records, the Cloudflare rules, the Turnstile widget,
GitHub's copy of the deploy secret, and the images on ghcr.io.

1. **Destroy** the old Droplet (or keep it switched off until the new one works, if it
   still runs; two connectors on one tunnel share the traffic, so don't run both).
2. Steps **1–3**: a new Droplet from `cloud-init.yaml` (from `main`), with **Monitoring**
   ticked, the tag `climpact` and your SSH key, then the SSH rule and the first-boot
   checks. cloud-init installs the deploy hook and its watcher, so D4 is not needed.
3. Step **5**, `climpact-init-env`: it makes a new Django key and Postgres password (the
   new database starts empty, so a new password is right) and asks for the **tunnel
   token**. Get it from **Zero Trust › Networks › Tunnels › climpact › Configure** (the
   Docker command), or **Refresh token**.
4. Put back the two secrets it doesn't make: `nano /opt/climpact/.env` and set
   - `DEPLOY_WEBHOOK_SECRET=` from the password manager (`climpact.app deploy hook`). If
     it is lost, make a new one and set it in GitHub too (D1).
   - `CLIMPACT_WEB_TURNSTILE_SITE_KEY=` and `CLIMPACT_WEB_TURNSTILE_SECRET_KEY=` from the
     password manager (`climpact.app Turnstile`), or the widget's **Settings** page.
5. Step **6** with the latest release: `/opt/climpact/update.sh X.Y.Z`. The tunnel shows
   **Healthy** again and the routes still point at `web` and `deploy-hook`.
6. Steps **7–8**: the smoke test, then close SSH and check the IP answers nothing. Run
   `bash deploy/check-edge.sh` from your computer: every line `PASS`.
7. Check that A2's graphs show memory and disk for the new Droplet, and that the uptime
   check is green.

A DigitalOcean **Rebuild** (same Droplet, fresh image) is not a shortcut: it keeps the
user data pasted at creation, which may be an older `cloud-init.yaml`.

## Moving it to other accounts (handover)

The same steps work in WMO's own DigitalOcean and Cloudflare accounts: the zone moves to
WMO's Cloudflare account (or the domain is transferred), and the tunnel, firewall and
Droplet are created there from this runbook, with the [Alerts](#alerts) in the new
DigitalOcean account and the deploy secret in a new `production` environment if the
repository moves. Then destroy the old Droplet and delete the old tunnel. No secret has
to be carried over: `climpact-init-env` makes the Django key and Postgres password, and
the tunnel, Turnstile widget and deploy secret are new in the new accounts (see
[Credentials](#credentials)). Jobs are short-lived, so no data needs moving either.
