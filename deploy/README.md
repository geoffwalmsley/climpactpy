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
| `cloudflare/*.txt` | The Cloudflare rule expressions, pasted into the dashboard (see [Cloudflare edge settings](#cloudflare-edge-settings)) |
| `check-edge.sh` | Checks the edge settings from your own computer |

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
ls -la /opt/climpact                         # compose.yaml and .env.example, owned by deploy
systemctl list-timers climpact-image-prune.timer apt-daily-upgrade.timer
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
   Published application routes › Add**.
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

`CLIMPACT_IMAGE` still reads `...:X.Y.Z` at this point. Step 6 sets it. The other settings
in `.env` (allowed host, upload limit, retention) have the right defaults for
`climpact.app`, and each one is described in the file.

## 6. Start the stack: after the release is published (about 5 min)

Use the latest release from <https://github.com/geoffwalmsley/climpactpy/releases> (its
*Release* workflow must have finished, because that is what pushes the image). The first
was **v0.1.0**, published on 2026-11-15.

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

In Cloudflare the tunnel should now show as connected (**Healthy**). Go back to step 4.4
to add the route and its DNS record.

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

What the free plan allows, and what this uses: 5 WAF custom rules (2 used), 1 rate
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

**Security › Security rules › Create rule › Custom rules**, twice:

| Rule name | Edit expression: paste the **contents** of | Action |
| --- | --- | --- |
| `Block scanner paths` | `deploy/cloudflare/waf-block.txt` | **Block** |
| `Challenge admin paths` | `deploy/cloudflare/waf-challenge.txt` | **Managed Challenge** |

**Deploy** each one. `waf-block.txt` blocks paths the app never serves: `*.php`, `*.asp`,
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

**Why a list of paths, and not "POSTs to `/station/`":** the free plan's rule can match the
**path only, not the method**. Its counter would therefore count every GET under a prefix like
`/station/`. The job pages poll their progress with htmx once a second
(`.../quality/progress`, `.../results/progress`, `/jobs/<id>/progress`,
`/batch/<id>/progress`), and form fields are checked with htmx POSTs as they change
(`.../load/validate`, `.../indices/validate`, `/batch/<id>/options`). A prefix rule would
block an ordinary visitor within 10 seconds of starting a job. `rate-limit.txt` lists only
the URLs that take an upload or start a job (upload and sample, *load*, *replace file*,
*run quality checks*, *replace file after QC*, *continue*, *indices*, *sector*, batch
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

**Security › Settings**, filter **Bot traffic** › **Bot fight mode:** On.

Bot Fight Mode challenges traffic that Cloudflare scores as automated. It **cannot be
skipped** by a custom rule, so nothing exempts the app's own requests. It also injects a
small script into the HTML pages (JavaScript detections, under `/cdn-cgi/challenge-platform/`).
The app sets no Content-Security-Policy, so nothing blocks that script. If one is ever
added, it must allow that path. A real browser that loaded the page passes the
detections, so its htmx requests carry the clearance and aren't challenged.

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
https://climpact.app/ | grep -i content-security` shows which header is sent.

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
Mode is classing `curl` from your network as a bot. That is not what browsers see: check
the pages in a browser instead (E8), and run the script from another network if you want a
clean run. Then do the browser walk-through of E8 and record the date and the results in
#124.

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
- Turnstile secret key: **Turnstile ›** the widget **› Settings › Rotate secret key**, put
  the new one in `.env`, then `docker compose up -d`.
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
