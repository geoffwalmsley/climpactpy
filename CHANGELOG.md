# Changelog

All notable changes to `climpact` and `climpact-web`, which are released together with one
version number ([RELEASING.md](RELEASING.md)). Versions follow
[Semantic Versioning](https://semver.org/); the format follows
[Keep a Changelog](https://keepachangelog.com/).

## Unreleased

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
