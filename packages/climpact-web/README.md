# climpact-web

The web front end for [climpactpy](https://github.com/geoffwalmsley/climpactpy), a Python
port of Climpact: a Django + htmx app. It depends on the core package (`climpactpy`,
imported as `climpact`); the core never imports it.

Only the skeleton exists so far; the screens are tracked under epic #11.

## Running it on your computer

```sh
pip install ./packages/climpact-web
climpact-web
```

`climpact-web` keeps its database and results in your user data folder, applies database
migrations, serves the app on http://127.0.0.1:8000/ and opens it in the browser. It needs
no network connection. Options: `--no-browser`, `--port`, `--host`, `--data-dir`,
`--threads`; `climpact-web manage <command>` runs a Django management command.

## Hosted mode

Set `CLIMPACT_WEB_MODE=hosted`, `CLIMPACT_WEB_SECRET_KEY`, `CLIMPACT_WEB_ALLOWED_HOSTS`,
`CLIMPACT_WEB_STATIC_ROOT` and `DATABASE_URL` (Postgres: install the `postgres` extra),
run `climpact-web manage migrate` and `climpact-web manage collectstatic`, and serve
`climpact_web.wsgi:application`. The health check is `/healthz`.

All settings are listed in TECHNICAL.md, section "Web front end".
