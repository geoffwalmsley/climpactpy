#!/bin/sh
# Entrypoint of the climpact-web image (#120). The first argument picks the role:
#
#   web             the WSGI server (waitress) on 0.0.0.0:8000 (default)
#   worker [args]   the background worker: `climpact-web manage runworker [args]`
#   migrate         apply database migrations
#   purge           delete expired jobs and fail jobs whose worker died (`purgejobs`)
#   manage <cmd>    any Django management command
#
# Anything else is run as a command (e.g. `sh`, for debugging). Every role exec's its
# process, so it is PID 1 and gets SIGTERM from `docker stop`.
set -eu

# matplotlib keeps its font cache in MPLCONFIGDIR and needs it writable; the root
# filesystem may be read-only, so copy the cache built into the image to the tmp dir.
if [ ! -d "$MPLCONFIGDIR" ]; then
    mkdir -p "$MPLCONFIGDIR" && cp -R /opt/climpact/mplconfig/. "$MPLCONFIGDIR"/
fi

role="${1:-web}"
[ "$#" -gt 0 ] && shift

case "$role" in
    web)
        exec climpact-web --host 0.0.0.0 --port "${CLIMPACT_WEB_PORT:-8000}" \
            --threads "${CLIMPACT_WEB_THREADS:-4}" --no-browser "$@"
        ;;
    worker)
        exec climpact-web manage runworker "$@"
        ;;
    migrate)
        exec climpact-web manage migrate --no-input "$@"
        ;;
    purge)
        exec climpact-web manage purgejobs "$@"
        ;;
    manage)
        exec climpact-web manage "$@"
        ;;
    *)
        exec "$role" "$@"
        ;;
esac
