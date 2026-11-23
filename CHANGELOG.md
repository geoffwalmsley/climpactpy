# Changelog

All notable changes to `climpact` and `climpact-web`, which are released together with one
version number ([RELEASING.md](RELEASING.md)). Versions follow
[Semantic Versioning](https://semver.org/); the format follows
[Keep a Changelog](https://keepachangelog.com/).

## Unreleased

## 0.2.0 - 2026-11-23

The web app is redesigned around **workspaces** for people who already know Climpact: a
workspace holds one station or a whole network, with its settings, quality checks, indices,
comparisons and files together. `climpact` gains gridded trends, multi-file gridded inputs
and a documented command line.

### Upgrading the hosted site

- **The upgrade deletes the stations and batches people have open** (decided on #231):
  they don't fit the workspace model, and their files go after the retention period. Its
  migrations can't be undone by deploying 0.1.3 again, so take a database dump first
  (`deploy/README.md` › "Backups" › "A dump by hand").
- **Paste `deploy/cloudflare/rate-limit.txt` into the rate-limiting rule again** (runbook
  E6): every job-starting address moved (#256, #271, #310, #360). Until then the old rule
  counts addresses that only redirect, and nothing that starts a job.
- New settings, with defaults that suit climpact.app: `CLIMPACT_WEB_WORKSPACE_EXPIRY` (on
  when hosted), `CLIMPACT_WEB_SPECULATIVE_MAX_QUEUED` (3) and `CLIMPACT_WEB_PUBLIC_URL`
  (`https://climpact.app` in `compose.yaml`). `CLIMPACT_WEB_MAX_DAILY_JOBS_PER_IP` now
  defaults to 50 (was 30), and the jobs of one change count as one.

### climpact

- Gridded trends (#290, #348): a gridded run can also write `trends.nc` (`--trends` on the
  command line), each cell's Sen's slope per decade, its 95% interval and base-period
  mean, and the grid mean, for annual and monthly indices. R's gridded code has no
  counterpart.
- A gridded variable split across many files (by year, say) is joined along time (#291).
- The command line's options have help text and metavars, and `climpact.cli.build_parser`
  is public, so the web help can document it (#319).

### Web app: workspaces

- Workspaces (#231, #253): a station or batch belongs to a workspace, which expires as a
  whole after its last change when hosted, and stays until deleted locally. The jobs a
  station shows are kept as long as it is.
- Workspace settings (#254): the base period, the quality thresholds and the index
  settings belong to the workspace. A change recalculates every station in it, as one
  change, and "Undo the change" puts the settings and the earlier results back while the
  recalculation is on the way. A station's own values from a metadata file stay its own.
- Add stations (#233, #271, #351): one page takes one station file, many, a
  metadata file or a zip, shows a review table checked in one pass, and adds them. It
  replaces the old New station and batch forms, whose addresses redirect to `/add/`. A
  quota refusal on one station makes nothing.
- A batch fills its workspace (#255, #311): every station of a batch is a station of the
  workspace, with its state (waiting, calculating, done, not run, failed and why).
- Addresses (#256): a workspace is `/w/<id>/` and a station's pages are under it
  (`/w/<id>/<station>/quality`, `.../indices`, `.../indices/<index>`). Old
  `/station/<id>/…` and `/batch/<id>/…` links redirect while their station is kept.
- The landing page, Get started and Workspaces, which lists every workspace of this
  browser, replace "Your calculations" (#242). A workspace's overview lists its stations
  and their verdicts, and a workspace with one station opens straight on it (#234, #298).
- Compare trends across stations in a trend grid, and overlay one index's series at every
  station (#238, #276, #279, #315).
- Files (#239, #269, #274, #307): one place for every download, with all-station CSVs and
  `climpact_run.json`, a record of what the results were made from. Hosted, a workspace
  can be kept 7 more days or deleted there.
- Save a workspace to a file and open it again, on this computer or another (#240). Copy
  a station to another workspace (#241).

### Web app: the station pages

- Quality is a short worklist with a verdict (Ready, Usable, Fix first), shown as list and
  detail with charts and per-check columns (#174, #202, #222, #235, #264, #308).
- Indices is one dense table across the whole window, with short names beside the codes,
  a detail pane, and a page per index with axes, the interval band and the annual values
  (#175, #200, #218, #236, #237, #263, #286).
- Calculation starts with the defaults while you look at the quality checks, and settings
  are adjusted and recalculated rather than resetting the station (#178, #179). Out-of-date
  results say so, and their header and downloads match what is shown (#223); a run that made
  no index table says there is nothing to show (#268).
- Inputs (the file, the station's details, the base period, the thresholds and the index
  settings) are one panel of sheets, and a new station has one setup page (#198, #199,
  #201).
- The charts are interactive again (#283); the read-out rounds an anomaly once (#349).
- Fixes: the web app labels TMge10 "TM of at least 10 °C" (R's catalogue says TX, but
  it counts TM days; #217); Enter in Add stations' review
  form checks the table and never adds (#318).

### Web app: look and help

- A new design for experts (`DESIGN.md`, #172, #232): colour tokens in light and dark,
  section headers with Help, a site header that stays in view, a phone layout, and one way
  of writing numbers and units (minus signs, decimals, coordinates) everywhere (#173,
  #189, #196, #197, #203, #226, #227, #284).
- The help is documentation (#177, #319, #325, #337, #342): a help frame with contents,
  a page per index, the command line and the file formats, which search engines may index
  on the hosted site (`/sitemap.xml`, `/robots.txt`); the guides follow Add stations and the
  workspace.
- Gridded runs (#289–#296, #301, #320, #321, #330): a list of runs and a run page with Map,
  Files and Set-up; a set-up page with a summary panel that chooses files from a folder
  listing; a map with an index rail, every cell, a coastline and a cell pane, with Base
  mean, Anomaly and Trend views and the grid mean, for annual and monthly files; the run's
  stages while it calculates and what to change when it fails. Local runs stay until
  forgotten. Gridded runs stay off on the hosted site.
- The English message catalogue is kept current (#205).

### Hosting

- The Cloudflare rate limit counts the new job-starting addresses (#310, #360), and a test
  fails when a job-starting view isn't counted. `compose.yaml` and `.env.example` name the
  same settings, which a test checks.
- Turnstile (#169): the "checking that you are a person" texts moved to `data-text-*`,
  since Turnstile reads `data-retry` as its own setting.

### Development

- The tests run in parallel with pytest-xdist (#181), and the browser accessibility checks
  are left out of the default run and faster (#180, #182).
- Pull requests that change the web app's look show screenshots, published to the
  `pr-screenshots` branch (`scripts/pr-screenshots.sh`).

## 0.1.3 - 2026-11-16

Changes to the hosted web app and the deployment docs. `climpact` itself is unchanged.

- Content Security Policy (#164): every page's policy now carries a per-request nonce in
  `script-src`, which Cloudflare copies onto the scripts it adds at the edge (its bot
  detection), so they run without violations; still no `'unsafe-inline'`. In hosted mode
  the policy also allows Cloudflare Web Analytics' beacon (new setting
  `CLIMPACT_WEB_CF_WEB_ANALYTICS`, default `true`; set `false` if the zone's Web
  Analytics is off).
- Turnstile (#163): a form sent before Cloudflare's check has finished is no longer
  refused with "Not accepted" (as with the sample's "Details look right" button on step
  1). The form waits, says it is checking that you are a person, and is sent as soon as
  the check finishes; if the check fails it says so and offers to try again.
- Operations (#127): the runbook (`deploy/README.md`) gains *Alerts* (DigitalOcean uptime
  check on `/healthz`, memory, disk and CPU alerts, a $15 billing alert), *Backups* (the
  decision: none, and a by-hand dump before a risky migration), *Credentials* (every
  secret, where it lives and how to rotate it) and *Operating the server* (rotating
  secrets, resizing, rebuilding from nothing). New Cloudflare skip rule
  `deploy/cloudflare/waf-skip-healthz.txt` so the uptime check is never challenged, and
  `deploy/check-edge.sh` checks that `/healthz` answers and is not cached.

## 0.1.2 - 2026-11-16

Changes to the web app and the deployment. `climpact` itself is unchanged.

- Content Security Policy (#137): every page of `climpact-web` (local and hosted) sends an
  enforced policy with no inline scripts or styles and no `eval`. The theme script, the
  chart skeleton's no-JS style and the `style=` attributes moved to files and classes, and
  htmx runs with eval and script tags off. Turnstile's `https://challenges.cloudflare.com`
  is allowed only when its keys are set. New setting `CLIMPACT_WEB_CSP_REPORT_ONLY`
  (default `false`): `true` reports violations in the browser console without blocking.
- Deploy on release (#126): publishing a final GitHub Release deploys it to climpact.app.
  The release workflow's new `deploy` job sends a signed request through the Cloudflare
  Tunnel to a deploy hook on the Droplet, which runs `deploy/update.sh` (fetch, pull,
  migrate, start, health check, automatic rollback) and waits until `/healthz` reports the
  new version. `update.sh` replaces `climpact-use`. The worker now gets 120 s to hand back
  its running job when stopped.

## 0.1.1 - 2026-11-16

Changes to the hosted web app (`climpact-web` in hosted mode, and its image). `climpact`
itself and the local `climpact-web` are unchanged.

- Abuse limits for the hosted site (#125), all off in local mode: Cloudflare Turnstile on
  the forms that upload a file or start a job (on when `CLIMPACT_WEB_TURNSTILE_SITE_KEY`
  and `_SECRET_KEY` are set); per-visitor quotas on jobs waiting or running and on jobs
  started in 24 hours, counted by Cloudflare's `CF-Connecting-IP`; no new jobs while the
  queue is full or the disk is low; a wall-clock limit on one job (60 minutes). Refusals
  show a plain page and are logged with the address and the reason. New settings:
  `CLIMPACT_WEB_MAX_ACTIVE_JOBS_PER_IP`, `_MAX_DAILY_JOBS_PER_IP`, `_MAX_QUEUED_JOBS`,
  `_MIN_FREE_DISK_GB`, `_JOB_TIME_LIMIT_MINUTES`. A database migration
  (`jobs/0002_abuse_limits`) runs on upgrade.
- Hosted mode sends `Strict-Transport-Security` with `includeSubDomains`, and every answer
  without its own `Cache-Control` is marked `private`, so Cloudflare never caches a
  visitor's downloads (#124).
- Deployment: `deploy/compose.yaml` passes the new settings and puts `web` on the
  `egress` network (for Turnstile's check), `deploy/.env.example` sends HSTS for a year,
  and the runbook covers the Cloudflare edge settings and the Turnstile keys.

## 0.1.0 - 2026-11-15

The first release on PyPI. The same code as 0.1.0rc1, which was published to TestPyPI
and checked; see that entry for what it contains.

## 0.1.0rc1 - 2026-11-15

The first release: the Python port of Climpact 3.4.3 and its web app.

- `climpact`: the Climpact indices of daily climate extremes for stations (single and
  batch runs), quality control, thresholds, trends, sector correlation and gridded
  (netCDF) data, written as Climpact's output files, with plots and a PDF report (the
  `plots` extra). Checked against R Climpact reference runs (see TECHNICAL.md for the
  parity status and the differences from R).
- `climpact-web`: the browser app for station, batch and gridded runs, on your own
  computer (`climpact-web`) or hosted (the `ghcr.io/geoffwalmsley/climpact-web` image).
- The core's distribution is named `climpact` (it was `climpactpy` during development,
  never published) and outputs credit "Climpact for Python X.Y.Z (port of Climpact
  3.4.3)". The gridded default file name template is now
  `var_daily_climpact_historical_NA_<first year>-<last year>.nc`.
