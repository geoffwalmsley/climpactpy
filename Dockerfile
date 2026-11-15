# syntax=docker/dockerfile:1
# The production image for climpact-web (#120): one image, run as `web`, `worker`, or a
# one-off command (`migrate`, `purge`, `manage ...`). See TECHNICAL.md › Deployment.
#
#   docker buildx build --platform linux/amd64 -t climpact-web --load .
#
# Pinned by digest; update both the tag and the digest together.
ARG PYTHON_IMAGE=python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------------------
# Builder: the virtualenv at /opt/venv from uv.lock (no dev groups), the collected static
# files and matplotlib's font cache.
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
WORKDIR /src

# Third-party dependencies first, from the lockfile alone, so this layer is reused until
# uv.lock or a pyproject.toml changes.
COPY pyproject.toml uv.lock ./
COPY packages/climpact/pyproject.toml packages/climpact/README.md packages/climpact/
COPY packages/climpact-web/pyproject.toml packages/climpact-web/README.md packages/climpact-web/
RUN uv sync --frozen --package climpact-web --extra postgres --no-default-groups \
        --no-install-workspace --no-editable

# Then the two workspace packages, installed as ordinary (non-editable) wheels, so the
# runtime image needs no source tree. The third-party packages' own test suites (pandas,
# scipy, numba, pyarrow, ...; about 150 MB) are never imported, so they are dropped.
COPY packages/climpact/src packages/climpact/src
COPY packages/climpact-web/src packages/climpact-web/src
RUN uv sync --frozen --package climpact-web --extra postgres --no-default-groups \
        --no-editable \
 && find /opt/venv/lib/python3.12/site-packages -depth -type d -name tests \
        -exec rm -rf {} +

# Static files are collected at build time, so the image is self-contained. The settings
# need the hosted variables to load; these values exist only in this build step.
RUN CLIMPACT_WEB_MODE=hosted \
    CLIMPACT_WEB_SECRET_KEY=build-only-not-a-secret \
    CLIMPACT_WEB_ALLOWED_HOSTS=localhost \
    CLIMPACT_WEB_STATIC_ROOT=/opt/climpact/static \
    DATABASE_URL=postgres://build@localhost/build \
    /opt/venv/bin/climpact-web manage collectstatic --no-input --verbosity 0 \
 && MPLCONFIGDIR=/opt/climpact/mplconfig /opt/venv/bin/python -c \
        "import matplotlib.font_manager as f; f.findfont('DejaVu Sans')"

# ---------------------------------------------------------------------------------------
# Runtime: Python, the virtualenv and the app's files; no compilers, uv or sources.
# The wheels bundle the native libraries (matplotlib, netCDF4/h5py, psycopg's libpq,
# numpy/scipy's OpenBLAS), so no system packages are added.
FROM ${PYTHON_IMAGE} AS runtime

# The source label links the package on ghcr.io to the repository (#122); CI adds the
# version and revision labels at build time (scripts/image.sh).
LABEL org.opencontainers.image.title="climpact-web" \
      org.opencontainers.image.description="Climpact climate indices web app (Python port of Climpact)" \
      org.opencontainers.image.source="https://github.com/geoffwalmsley/climpactpy" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

RUN groupadd --system --gid 10001 climpact \
 && useradd --system --uid 10001 --gid climpact --no-create-home --home-dir /tmp \
        --shell /usr/sbin/nologin climpact \
 && mkdir -p /var/lib/climpact/media \
 && chown -R climpact:climpact /var/lib/climpact

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/climpact /opt/climpact
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/climpact-entrypoint
COPY --chmod=0755 docker/healthcheck.py /usr/local/bin/climpact-healthcheck

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache \
    HOME=/tmp \
    CLIMPACT_WEB_MODE=hosted \
    CLIMPACT_WEB_STATIC_ROOT=/opt/climpact/static \
    CLIMPACT_WEB_DATA_DIR=/var/lib/climpact \
    CLIMPACT_WEB_MEDIA_ROOT=/var/lib/climpact/media \
    CLIMPACT_WEB_TRUSTED_PROXY=*

# CLIMPACT_WEB_TRUSTED_PROXY=* trusts X-Forwarded-Proto/-For from any peer: only the
# tunnel (cloudflared) can reach port 8000, which is never published on the host. Set it to
# the proxy's address instead where other hosts can reach the container.
USER climpact:climpact
WORKDIR /var/lib/climpact
EXPOSE 8000

# The web role answers /healthz; other roles report healthy (the script checks PID 1).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["climpact-healthcheck"]

ENTRYPOINT ["climpact-entrypoint"]
CMD ["web"]
