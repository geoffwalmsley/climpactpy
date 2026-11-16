#!/bin/sh
# deploy/call-hook.sh: ask climpact.app to deploy a release, and wait for it (#126). The
# release workflow's `deploy` job runs it; it also works from your own computer.
#
#   DEPLOY_WEBHOOK_SECRET=... deploy/call-hook.sh post X.Y.Z
#       signs {"version": "X.Y.Z"} and POSTs it to $DEPLOY_HOOK_URL
#       (default https://climpact.app/_deploy); succeeds on 202
#   deploy/call-hook.sh wait X.Y.Z
#       polls $HEALTHZ_URL (default https://climpact.app/healthz) every $DEPLOY_POLL s
#       (default 10) until it reports X.Y.Z, or fails after $DEPLOY_TIMEOUT s (default 600)
#
# The signature: X-Climpact-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>">
# with the secret as key, and the timestamp in X-Climpact-Timestamp (deploy/deploy-hook.py
# checks both). Needs only sh, curl and openssl.
set -eu
export LC_ALL=C

HOOK_URL="${DEPLOY_HOOK_URL:-https://climpact.app/_deploy}"
HEALTHZ_URL="${HEALTHZ_URL:-https://climpact.app/healthz}"
TIMEOUT="${DEPLOY_TIMEOUT:-600}"
POLL="${DEPLOY_POLL:-10}"
UA="climpact-deploy/1 (curl)"
RUNBOOK="deploy/README.md > Deploy on release"

# An annotation in GitHub Actions, a plain line elsewhere.
error() {
  if [ "${GITHUB_ACTIONS:-}" = true ]; then echo "::error title=Deploy::$*"; else echo "ERROR: $*"; fi
}
usage() { echo "usage: call-hook.sh post|wait X.Y.Z" >&2; exit 2; }

[ "$#" = 2 ] || usage
version="$2"
case "$version" in "" | *[!0-9.]*) error "'$version' is not a version X.Y.Z"; exit 2 ;; esac
printf '%s\n' "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || { error "'$version' is not a version X.Y.Z"; exit 2; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

post() {
  [ -n "${DEPLOY_WEBHOOK_SECRET:-}" ] || { error "DEPLOY_WEBHOOK_SECRET is not set (see $RUNBOOK)"; exit 1; }
  body=$(printf '{"version": "%s"}' "$version")
  ts=$(date +%s)
  sig=$(printf '%s.%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$DEPLOY_WEBHOOK_SECRET" | awk '{ print $NF }')
  echo "POST $HOOK_URL $body"
  code=$(curl -sS -o "$tmp/body" -D "$tmp/headers" -w '%{http_code}' -A "$UA" \
    --max-time 30 --retry 3 --retry-delay 5 -X POST \
    -H "Content-Type: application/json" \
    -H "X-Climpact-Timestamp: $ts" \
    -H "X-Climpact-Signature: sha256=$sig" \
    --data-binary "$body" "$HOOK_URL") || code=000
  answer=$(head -c 500 "$tmp/body" 2>/dev/null || true)
  echo "HTTP $code $answer"
  case "$code" in
    202) echo "The Droplet accepted the deploy of $version."; return 0 ;;
  esac
  if grep -qi '^cf-mitigated: *challenge' "$tmp/headers" 2>/dev/null; then
    error "Cloudflare challenged the request (Bot Fight Mode or a WAF rule), so it never reached the Droplet. See $RUNBOOK."
  elif ! printf '%s' "$answer" | grep -q '"hook": "climpact-deploy"'; then
    case "$code" in
      000) error "no answer from $HOOK_URL" ;;
      502 | 503 | 504 | 530) error "HTTP $code from Cloudflare: the tunnel could not reach the deploy-hook service (is it running? docker compose ps on the Droplet)" ;;
      *) error "HTTP $code, not from the deploy hook: the tunnel route for /_deploy is missing, or a Cloudflare rule answered. See $RUNBOOK." ;;
    esac
  else
    case "$code" in
      401) error "the deploy hook refused the signature: DEPLOY_WEBHOOK_SECRET differs between GitHub and the Droplet's .env (or a clock is more than 5 minutes off)" ;;
      503) error "the deploy hook has no DEPLOY_WEBHOOK_SECRET: set it in /opt/climpact/.env, then docker compose up -d" ;;
      *) error "the deploy hook answered HTTP $code: $answer" ;;
    esac
  fi
  return 1
}

wait_live() {
  echo "Waiting up to $TIMEOUT s for $HEALTHZ_URL to report $version"
  start=$(date +%s)
  last=
  while :; do
    code=$(curl -sS -o "$tmp/body" -D "$tmp/headers" -w '%{http_code}' -A "$UA" \
      --max-time 10 "$HEALTHZ_URL" 2>/dev/null) || code=000
    live=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$tmp/body" 2>/dev/null | head -n 1)
    now="HTTP $code, version ${live:-?}"
    [ "$now" = "$last" ] || echo "$(($(date +%s) - start)) s: $now"
    last=$now
    if [ "$code" = 200 ] && [ "$live" = "$version" ]; then
      echo "climpact.app runs $version."
      return 0
    fi
    if grep -qi '^cf-mitigated: *challenge' "$tmp/headers" 2>/dev/null; then
      error "Cloudflare challenges the requests to /healthz from this runner (Bot Fight Mode). See $RUNBOOK."
      return 1
    fi
    if [ $(($(date +%s) - start)) -ge "$TIMEOUT" ]; then
      error "climpact.app still reports ${live:-no version} after $TIMEOUT s, not $version: the deploy failed and was rolled back, or is still running. On the Droplet: journalctl -u climpact-deploy; tail /opt/climpact/deploy.log"
      return 1
    fi
    sleep "$POLL"
  done
}

case "$1" in
  post) post ;;
  wait) wait_live ;;
  *) usage ;;
esac
