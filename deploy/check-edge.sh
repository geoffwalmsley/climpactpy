#!/usr/bin/env bash
# Check climpact.app's Cloudflare edge settings from outside (#124). Run it on your own
# computer after applying deploy/README.md > "Cloudflare edge settings":
#
#   bash deploy/check-edge.sh                 # every check except the burst
#   bash deploy/check-edge.sh --burst         # also fire 25 POSTs to test the rate limit
#
# Read-only apart from --burst, whose POSTs carry no CSRF token: the app refuses each one
# (403) before doing anything, so no job is started. The burst blocks your IP address on
# the job-starting paths for 10 seconds, nothing else. Needs only curl (macOS has it).
# Each line prints PASS, FAIL or NOTE; deploy/README.md says what to do about a FAIL.

set -u
HOST="${CLIMPACT_HOST:-climpact.app}"
SITE="https://$HOST"
BURST=0
[ "${1:-}" = "--burst" ] && BURST=1
UA="climpact-edge-check/1 (curl)"
fails=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }
note() { printf 'NOTE  %s\n' "$1"; }

# fetch_headers URL [curl options...]: the response headers, lower-cased names.
fetch_headers() {
  local url="$1"
  shift
  curl -sS -o /dev/null -D - -A "$UA" --max-time 15 "$@" "$url" 2>/dev/null | tr -d '\r' |
    awk -F': ' 'NR == 1 { print; next } { printf "%s: %s\n", tolower($1), substr($0, length($1) + 3) }'
}
status() { fetch_headers "$@" | awk 'NR == 1 { print $2 }'; }
header() { awk -v name="$1" -F': ' '$1 == name { print substr($0, length($1) + 3) }'; }

echo "== $SITE"

# --- TLS and redirects ---------------------------------------------------------------
if curl -sS -o /dev/null -A "$UA" --max-time 15 --tlsv1.2 --tls-max 1.2 "$SITE/healthz"; then
  pass "TLS 1.2 accepted"
else
  fail "TLS 1.2 refused (Minimum TLS Version should be 1.2, not 1.3)"
fi
if curl -sS -o /dev/null -A "$UA" --max-time 15 --tlsv1.1 --tls-max 1.1 "$SITE/healthz" 2>/dev/null; then
  fail "TLS 1.1 accepted (set Minimum TLS Version to TLS 1.2)"
else
  pass "TLS 1.1 refused (also passes if your curl cannot speak TLS 1.1)"
fi

h=$(fetch_headers "http://$HOST/station/?x=1")
loc=$(printf '%s\n' "$h" | header location)
case "$(printf '%s\n' "$h" | awk 'NR==1{print $2}') $loc" in
  "301 https://$HOST/station/?x=1" | "308 https://$HOST/station/?x=1") pass "http:// -> $loc" ;;
  *) fail "http://$HOST/station/?x=1 gave: $(printf '%s\n' "$h" | head -n 1) $loc" ;;
esac

h=$(fetch_headers "https://www.$HOST/help/?x=1")
code=$(printf '%s\n' "$h" | awk 'NR==1{print $2}')
loc=$(printf '%s\n' "$h" | header location)
if [ "$code" = 301 ] && [ "$loc" = "https://$HOST/help/?x=1" ]; then
  pass "https://www.$HOST/help/?x=1 -> 301 $loc"
elif [ -z "$code" ]; then
  fail "https://www.$HOST does not answer (no proxied DNS record for www?)"
else
  fail "https://www.$HOST/help/?x=1 gave ${code} ${loc:-no Location} (want 301 https://$HOST/help/?x=1)"
fi
end=$(curl -sS -o /dev/null -L -A "$UA" --max-time 15 -w '%{http_code} %{url_effective}' "http://www.$HOST/help/?x=1" 2>/dev/null)
[ "$end" = "200 https://$HOST/help/?x=1" ] && pass "http://www.$HOST/help/?x=1 ends at $end" ||
  fail "http://www.$HOST/help/?x=1 ends at '${end}' (want 200 https://$HOST/help/?x=1)"

# --- Headers the app sends -------------------------------------------------------------
h=$(fetch_headers "$SITE/")
hsts=$(printf '%s\n' "$h" | header strict-transport-security)
case "$hsts" in
  "max-age=31536000; includeSubDomains") pass "HSTS: $hsts" ;;
  "max-age=31536000") note "HSTS: $hsts (includeSubDomains comes with the first release after #124)" ;;
  "") fail "no Strict-Transport-Security (set CLIMPACT_WEB_HSTS_SECONDS=31536000 in /opt/climpact/.env)" ;;
  *) fail "HSTS: $hsts (want max-age=31536000; includeSubDomains)" ;;
esac
if [ "$(printf '%s\n' "$h" | grep -c '^strict-transport-security:')" -gt 1 ]; then
  fail "two Strict-Transport-Security headers: turn off Cloudflare's HSTS (the app sends it)"
fi
code=$(printf '%s\n' "$h" | awk 'NR==1{print $2}')
mit=$(printf '%s\n' "$h" | header cf-mitigated)
if [ "$code" = 200 ] && [ -z "$mit" ]; then
  pass "home page 200, not challenged"
else
  fail "home page gave $code ${mit:+(cf-mitigated: $mit)}; see README if only curl is challenged"
fi

# --- Caching ----------------------------------------------------------------------------
css=$(curl -sS -A "$UA" --max-time 15 "$SITE/" | grep -oE '/static/[^"]+\.css' | head -n 1)
if [ -z "$css" ]; then
  fail "no stylesheet link found on the home page"
else
  fetch_headers "$SITE$css" >/dev/null
  h=$(fetch_headers "$SITE$css")
  cs=$(printf '%s\n' "$h" | header cf-cache-status)
  [ "$cs" = HIT ] && pass "second request for $css: cf-cache-status: HIT" ||
    fail "second request for $css: cf-cache-status: ${cs:-none} (want HIT)"
fi
for path in / /station/sample.txt; do
  h=$(fetch_headers "$SITE$path")
  cs=$(printf '%s\n' "$h" | header cf-cache-status)
  cc=$(printf '%s\n' "$h" | header cache-control)
  case "$cs" in
    HIT | MISS | EXPIRED | STALE | REVALIDATED | UPDATING)
      fail "$path cf-cache-status: $cs (only /static/ may be cached; check the cache rules)" ;;
    *) pass "$path not cached at the edge (cf-cache-status: ${cs:-none}; cache-control: ${cc:-none})" ;;
  esac
done

# --- WAF custom rules ---------------------------------------------------------------------
for path in /wp-login.php /.env /.git/config /cgi-bin/test; do
  code=$(status "$SITE$path")
  [ "$code" = 403 ] && pass "$path blocked (403)" || fail "$path gave $code (want 403 from the block rule)"
done
code=$(status "$SITE/.well-known/security.txt")
[ "$code" = 404 ] && pass "/.well-known/ not blocked (404 from the app)" ||
  fail "/.well-known/security.txt gave $code (want the app's 404)"
h=$(fetch_headers "$SITE/admin/")
mit=$(printf '%s\n' "$h" | header cf-mitigated)
[ "$mit" = challenge ] && pass "/admin/ challenged (cf-mitigated: challenge)" ||
  fail "/admin/ gave $(printf '%s\n' "$h" | head -n 1) ${mit:+cf-mitigated: $mit} (want a managed challenge)"

# --- Normal pages and htmx polls are not challenged -------------------------------------
for path in /add/ /w/ /help/ /jobs/; do
  h=$(fetch_headers "$SITE$path")
  code=$(printf '%s\n' "$h" | awk 'NR==1{print $2}')
  mit=$(printf '%s\n' "$h" | header cf-mitigated)
  if [ "$code" = 200 ] && [ -z "$mit" ]; then pass "GET $path 200"; else
    fail "GET $path gave $code ${mit:+(cf-mitigated: $mit)}"; fi
done
# An htmx poll of a job that does not exist: the app's 404, not a challenge or a 429.
h=$(fetch_headers "$SITE/jobs/00000000-0000-0000-0000-000000000000/progress" -H "HX-Request: true")
code=$(printf '%s\n' "$h" | awk 'NR==1{print $2}')
[ "$code" = 404 ] && pass "htmx-style poll reaches the app (404 for a made-up job)" ||
  fail "htmx-style poll gave $code $(printf '%s\n' "$h" | header cf-mitigated)"

# --- The uptime check's URL (#127) ------------------------------------------------------
# DigitalOcean's Uptime check fetches /healthz from cloud addresses: it must reach the app
# every time (not challenged, not served from the edge cache). Asked twice, so a cached
# first answer would show as a HIT on the second.
fetch_headers "$SITE/healthz" >/dev/null
h=$(fetch_headers "$SITE/healthz")
code=$(printf '%s\n' "$h" | awk 'NR==1{print $2}')
mit=$(printf '%s\n' "$h" | header cf-mitigated)
cs=$(printf '%s\n' "$h" | header cf-cache-status)
cc=$(printf '%s\n' "$h" | header cache-control)
body=$(curl -sS -A "$UA" --max-time 15 "$SITE/healthz" 2>/dev/null)
if [ "$code" != 200 ] || [ -n "$mit" ]; then
  fail "GET /healthz gave $code ${mit:+(cf-mitigated: $mit)}; the uptime check would report the site down"
else
  case "$cs" in
    HIT | MISS | EXPIRED | STALE | REVALIDATED | UPDATING)
      fail "/healthz cf-cache-status: $cs (it must never be cached; check the cache rules)" ;;
    *)
      case "$body" in
        *'"status": "ok"'*) pass "/healthz 200, ok, not cached (cf-cache-status: ${cs:-none}; cache-control: ${cc:-none})" ;;
        *) fail "/healthz 200 but not ok: $body" ;;
      esac ;;
  esac
fi

# --- Rate limit -------------------------------------------------------------------------
if [ "$BURST" = 1 ]; then
  url="$SITE/jobs/00000000-0000-0000-0000-000000000000/retry"
  # Sequential, and 25 of them: Cloudflare updates its counters asynchronously, so the
  # block starts somewhere after the 10th request (in tests: the 11th to the 15th), and a
  # burst sent all at once can slip through before the counter catches up.
  codes=""
  for _ in $(seq 1 25); do
    codes="$codes $(curl -sS -o /dev/null -w '%{http_code}' -A "$UA" --max-time 15 -X POST "$url")"
  done
  echo "      25 POSTs to /jobs/<id>/retry:$codes"
  case "$codes" in
    *429*) pass "burst blocked by the rate limit (429 after about 10 requests)" ;;
    *) fail "no 429 in the burst: check the rate limiting rule is deployed" ;;
  esac
  echo "      waiting 12 s for the block to end..."
  sleep 12
  code=$(curl -sS -o /dev/null -w '%{http_code}' -A "$UA" --max-time 15 -X POST "$url")
  [ "$code" = 403 ] && pass "after the block: 403 from the app again (no CSRF token)" ||
    fail "after the block: $code (want 403)"
else
  note "rate limit not tested; run with --burst to fire 25 POSTs"
fi

echo
if [ "$fails" = 0 ]; then echo "All checks passed."; else echo "$fails check(s) failed."; fi
exit $((fails > 0))
