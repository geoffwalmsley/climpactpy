# climpact-web

The web front end for [climpactpy](https://github.com/geoffwalmsley/climpactpy), a Python
port of Climpact: a Django + htmx app. It depends on the core package (`climpactpy`,
imported as `climpact`); the core never imports it.

The skeleton, the design system and the landing page exist so far; the screens are
tracked under epic #11. With `CLIMPACT_WEB_DEBUG=true` (or
`CLIMPACT_WEB_PATTERN_LIBRARY=true`) the pattern library at `/patterns/` shows every UI
component.

## Running it on your computer

```sh
pip install ./packages/climpact-web
climpact-web
```

In a checkout of the repository, `uv sync` then `uv run climpact-web` does the same with
the locked versions.

`climpact-web` keeps its database and results in your user data folder, applies database
migrations, starts a background worker for the calculations, serves the app on
http://127.0.0.1:8000/ and opens it in the browser. It needs no network connection.
Options: `--no-browser`, `--port`, `--host`, `--data-dir`, `--threads`, `--no-worker`;
`climpact-web manage <command>` runs a Django management command. Uploads and results are
deleted after 7 days (`CLIMPACT_WEB_RETENTION_DAYS`).

## Changing the styles

The stylesheet is written for Tailwind CSS and built by the standalone Tailwind CLI (#118);
the built file, `core/static/climpact_web/css/climpact.css`, is committed, so running or
installing the app needs no Tailwind. To change a template's classes or the source in
`core/tailwind/`, from the repository root:

```sh
scripts/fetch-tailwind.sh                     # once: the pinned CLI into bin/, checksum checked
scripts/build-css.sh --watch                  # rebuild on every change
CLIMPACT_WEB_DEBUG=true uv run climpact-web   # in another terminal: changes show on reload
scripts/build-css.sh                          # one build before committing
```

CI rebuilds the stylesheet and fails if the committed file differs. Utilities go in the
templates; repeated pieces, and classes built in Python or JavaScript, are components in
`core/tailwind/components/`. See TECHNICAL.md, "Stylesheet and Tailwind".

## Hosted mode

Set `CLIMPACT_WEB_MODE=hosted`, `CLIMPACT_WEB_SECRET_KEY`, `CLIMPACT_WEB_ALLOWED_HOSTS`,
`CLIMPACT_WEB_STATIC_ROOT` and `DATABASE_URL` (Postgres: install the `postgres` extra),
run `climpact-web manage migrate` and `climpact-web manage collectstatic`, and serve
`climpact_web.wsgi:application`. Run one or more `climpact-web manage runworker`
processes for the background jobs. The health check is `/healthz`.

All settings are listed in TECHNICAL.md, section "Web front end".
