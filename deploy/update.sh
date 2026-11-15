#!/bin/sh
# /opt/climpact/update.sh: deploy a climpact release on the Droplet (#126). The only way
# the app is updated or rolled back, by hand or from the release workflow's deploy hook.
#
#   update.sh X.Y.Z                 deploy release vX.Y.Z (as deploy; vX.Y.Z also works)
#   update.sh --hook                deploy the version the deploy hook queued in
#                                   hook/request (run by climpact-deploy.service)
#   update.sh --fetch vX.Y.Z|main   only fetch the deploy files of that tag or main
#   sudo update.sh --install-hook   once per Droplet: the hook's drop folder and the
#                                   systemd units climpact-deploy.path and .service
#
# A deploy, one at a time (a second one waits for the lock):
#   1. Fetch compose.yaml, .env.example, deploy-hook.py and update.sh from the release's
#      tag, and pull ghcr.io/geoffwalmsley/climpact-web:X.Y.Z (public: no login). A
#      failure here changes nothing.
#   2. Keep the current files and CLIMPACT_IMAGE in .previous/, then put the new files in
#      place and pin CLIMPACT_IMAGE in .env to the new image.
#   3. `docker compose run --rm migrate`, then `docker compose up -d --wait`.
#   4. Ask /healthz inside the web container until it reports X.Y.Z.
#   If 3 or 4 fails: put .previous/ back, start it, check it, and log ROLLED BACK (exit 1).
#   Migrations are not reversed: a release's migrations must work with the previous code.
#   5. Remove the app images other than the new and the previous one.
#
# Logs go to stderr (the journal of climpact-deploy.service when the hook runs it; by
# hand, logger's tag climpact-deploy too) and /opt/climpact/deploy.log.
# deploy/README.md (the runbook) and TECHNICAL.md > Deployment describe the whole setup.
set -eu
export LC_ALL=C

REPO="${CLIMPACT_REPO:-geoffwalmsley/climpactpy}"
IMAGE_REPO="${CLIMPACT_IMAGE_REPO:-ghcr.io/geoffwalmsley/climpact-web}"
DIR="${CLIMPACT_DIR:-/opt/climpact}"
DEPLOY_USER="${CLIMPACT_DEPLOY_USER:-deploy}"
HOOK_UID=10001                                      # the deploy-hook container's user
HEALTH_TIMEOUT="${CLIMPACT_HEALTH_TIMEOUT:-180}"    # s for /healthz to report the version
HEALTH_INTERVAL="${CLIMPACT_HEALTH_INTERVAL:-5}"
WAIT_TIMEOUT="${CLIMPACT_WAIT_TIMEOUT:-300}"        # s for `up --wait`
LOCK_WAIT="${CLIMPACT_LOCK_WAIT:-3600}"             # s to wait for another deploy
FILES="compose.yaml .env.example deploy-hook.py update.sh"
REQUIRED="compose.yaml .env.example"                # older releases lack the other two

# Under systemd (INVOCATION_ID set) stderr already goes to the journal; by hand, logger.
to_journal() {
  if [ -z "${INVOCATION_ID:-}" ] && command -v logger >/dev/null 2>&1; then
    logger -t climpact-deploy "$@" || true
  fi
}
log() {
  echo "climpact-update: $*" >&2
  to_journal -- "$*"
  if [ -w "$DIR" ]; then echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $*" >>"$DIR/deploy.log" || true; fi
}
loud() {
  echo "climpact-update: !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  echo "climpact-update: !!! $*" >&2
  echo "climpact-update: !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  to_journal -p user.err -- "$*"
  if [ -w "$DIR" ]; then echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') ERROR $*" >>"$DIR/deploy.log" || true; fi
}
die() { log "$*"; exit 1; }
usage() {
  echo "usage: update.sh X.Y.Z | --hook | --fetch vX.Y.Z|main | --install-hook" >&2
  exit 2
}

# X.Y.Z with ASCII digits, nothing else (no newline, no suffix).
valid_version() {
  case "$1" in "" | *[!0-9.]*) return 1 ;; esac
  printf '%s\n' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'
}

# .env helpers (the same awk as climpact-init-env): read and set one KEY=value line.
env_get() { K="$1" awk 'index($0, ENVIRON["K"] "=") == 1 { v = substr($0, length(ENVIRON["K"]) + 2) } END { print v }' .env; }
env_set() {
  (
    umask 077
    K="$1" V="$2" awk '
      index($0, ENVIRON["K"] "=") == 1 { print ENVIRON["K"] "=" ENVIRON["V"]; done = 1; next }
      { print }
      END { if (!done) print ENVIRON["K"] "=" ENVIRON["V"] }' .env >.env.new
  )
  mv .env.new .env
}

as_deploy_user() {
  [ "$(id -un)" = "$DEPLOY_USER" ] || die "run as $DEPLOY_USER (sudo -iu $DEPLOY_USER)"
}

lock() {
  exec 9>"$DIR/.deploy.lock"
  if ! flock -n 9; then
    log "another deploy is running; waiting for it to finish"
    flock -w "$LOCK_WAIT" 9 || die "gave up waiting for the other deploy after $LOCK_WAIT s"
  fi
}

# fetch REF DEST: the deploy files of tag REF (or main) into DEST.
fetch() {
  for f in $FILES; do
    url="https://raw.githubusercontent.com/$REPO/$1/deploy/$f"
    rc=0
    curl -fsSL --retry 3 "$url" -o "$2/$f" || rc=$?
    if [ "$rc" != 0 ]; then
      rm -f "$2/$f"
      case " $REQUIRED " in
        *" $f "*) log "could not fetch $url (is $1 published?)"; return 1 ;;
      esac
      [ "$rc" = 22 ] || { log "could not fetch $url"; return 1; }
      log "$1 has no deploy/$f (an older release): keeping the current one"
    fi
  done
}

# install_files SRC: move the files in SRC into DIR (rename: a running update.sh keeps
# reading its own, old copy).
install_files() {
  for f in $FILES; do
    [ -f "$1/$f" ] || continue
    case "$f" in update.sh) chmod 0755 "$1/$f" ;; *) chmod 0644 "$1/$f" ;; esac
    mv -f "$1/$f" "$DIR/$f"
  done
}

# check_health VERSION: /healthz inside web answers 200 and reports VERSION (any version
# when VERSION is empty), within HEALTH_TIMEOUT seconds.
HEALTH_PY='
import json, os, urllib.request
hosts = [h.strip().lstrip(".") for h in os.environ.get("CLIMPACT_WEB_ALLOWED_HOSTS", "").split(",")]
host = next((h for h in hosts if h and h != "*"), "localhost")
port = os.environ.get("CLIMPACT_WEB_PORT", "8000")
req = urllib.request.Request(f"http://127.0.0.1:{port}/healthz", headers={"Host": host})
print(json.load(urllib.request.urlopen(req, timeout=5))["version"])
'
check_health() {
  waited=0
  live=
  while :; do
    live=$(docker compose exec -T web python -I -c "$HEALTH_PY" 2>/dev/null) || live=
    if [ -n "$live" ] && { [ -z "$1" ] || [ "$live" = "$1" ]; }; then
      log "/healthz reports version $live"
      return 0
    fi
    [ "$waited" -lt "$HEALTH_TIMEOUT" ] || break
    sleep "$HEALTH_INTERVAL"
    waited=$((waited + HEALTH_INTERVAL))
  done
  loud "/healthz did not report version ${1:-(any)} within $HEALTH_TIMEOUT s (last: ${live:-no answer})"
  return 1
}

# start VERSION: migrate, start the stack, check it.
start() {
  if ! docker compose run --rm -T migrate; then
    loud "migrate failed with the new image"
    return 1
  fi
  if ! docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT"; then
    loud "docker compose up did not get every service running and healthy"
    return 1
  fi
  if [ -n "$hook_changed" ]; then
    # The script is bind-mounted as a file: a restart mounts the new one.
    docker compose restart deploy-hook >/dev/null 2>&1 || log "could not restart deploy-hook"
  fi
  check_health "$1"
}

rollback() {
  loud "deploy of $version FAILED; rolling back to ${prev_image:-nothing}"
  case "$prev_image" in
    "" | *X.Y.Z)
      loud "there is no previous release to roll back to: the stack is left as it is"
      return 1 ;;
  esac
  if [ ! -f .previous/compose.yaml ]; then
    loud "no .previous/compose.yaml: the stack is left as it is"
    return 1
  fi
  restore=$(mktemp -d "$DIR/.restore.XXXXXX")
  for f in $FILES; do [ ! -f ".previous/$f" ] || cp -p ".previous/$f" "$restore/$f"; done
  install_files "$restore"
  rmdir "$restore" 2>/dev/null || rm -rf "$restore"
  env_set CLIMPACT_IMAGE "$prev_image"
  prev_version="${prev_image##*:}"
  valid_version "$prev_version" || prev_version=
  if docker compose up -d --wait --wait-timeout "$WAIT_TIMEOUT" && check_health "$prev_version"; then
    [ -z "$hook_changed" ] || docker compose restart deploy-hook >/dev/null 2>&1 || true
    loud "ROLLED BACK to $prev_image; $version is NOT deployed"
  else
    loud "ROLLBACK to $prev_image FAILED TOO: the site may be down (docker compose ps; docker compose logs web)"
  fi
  return 1
}

prune() {
  docker image ls "$IMAGE_REPO" --format '{{.Repository}}:{{.Tag}}' 2>/dev/null |
    while read -r ref; do
      case "$ref" in "$image" | "$prev_image" | *:"<none>") continue ;; esac
      if docker image rm "$ref" >/dev/null 2>&1; then log "removed image $ref"; fi
    done
  docker image prune -f >/dev/null 2>&1 || true
}

deploy() {
  version="$1"
  image="$IMAGE_REPO:$version"
  cd "$DIR"
  [ -f .env ] || die "no $DIR/.env yet: run climpact-init-env first"
  lock
  prev_image=$(env_get CLIMPACT_IMAGE)
  log "deploying $version (running: ${prev_image:-nothing})"

  staging=$(mktemp -d "$DIR/.staging.XXXXXX")
  trap 'rm -rf "$staging"' EXIT
  fetch "v$version" "$staging" || die "deploy of $version stopped before changing anything"
  if ! docker pull -q "$image" >/dev/null; then
    die "could not pull $image (is the release's image published?); nothing changed"
  fi

  rm -rf .previous.new
  mkdir .previous.new
  for f in $FILES; do [ ! -f "$f" ] || cp -p "$f" .previous.new/; done
  echo "$prev_image" >.previous.new/image
  rm -rf .previous
  mv .previous.new .previous

  hook_changed=
  if [ -f "$staging/deploy-hook.py" ] && ! cmp -s "$staging/deploy-hook.py" deploy-hook.py; then
    hook_changed=1
  fi
  install_files "$staging"
  env_set CLIMPACT_IMAGE "$image"
  [ -d hook ] || log "WARNING: no $DIR/hook: the deploy hook is off (sudo $DIR/update.sh --install-hook)"

  if start "$version"; then
    prune
    log "deployed $version"
    return 0
  fi
  rollback
}

# --hook: the version queued by deploy-hook.py, checked again here.
from_hook() {
  request="$DIR/hook/request"
  if [ ! -f "$request" ]; then
    log "no deploy request in $request"
    return 0
  fi
  version=$(head -c 64 "$request" | tr -d '\n')
  rm -f "$request"
  valid_version "$version" || die "the deploy hook queued an invalid version; ignored"
  log "the deploy hook asked for $version"
  deploy "$version"
}

install_hook() {
  [ "$(id -u)" = 0 ] || die "--install-hook needs root: sudo $0 --install-hook"
  install -d -m 2770 -o "$HOOK_UID" -g "$DEPLOY_USER" "$DIR/hook"
  units="${CLIMPACT_SYSTEMD_DIR:-/etc/systemd/system}"
  cat >"$units/climpact-deploy.path" <<EOF
# climpact (#126): deploy a release when the deploy hook queues one. Written by
# $DIR/update.sh --install-hook.
[Unit]
Description=Watch for deploy requests from the deploy hook (climpact)

[Path]
PathExists=$DIR/hook/request
Unit=climpact-deploy.service

[Install]
WantedBy=multi-user.target
EOF
  cat >"$units/climpact-deploy.service" <<EOF
# climpact (#126): one deploy at a time; a request made meanwhile runs next. Written by
# $DIR/update.sh --install-hook.
[Unit]
Description=Deploy the release the deploy hook asked for (climpact)
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
User=$DEPLOY_USER
Group=$DEPLOY_USER
WorkingDirectory=$DIR
ExecStart=$DIR/update.sh --hook
TimeoutStartSec=30min
EOF
  chmod 0644 "$units/climpact-deploy.path" "$units/climpact-deploy.service"
  if [ -z "${CLIMPACT_BOOTSTRAP_NO_SYSTEMD:-}" ]; then
    systemctl daemon-reload
    systemctl enable --now climpact-deploy.path
  fi
  echo "climpact-update: $DIR/hook and climpact-deploy.path installed"
}

case "${1:-}" in
  --hook)
    [ "$#" = 1 ] || usage
    as_deploy_user
    from_hook ;;
  --fetch)
    [ "$#" = 2 ] || usage
    case "$2" in main) ;; v*) valid_version "${2#v}" || usage ;; *) usage ;; esac
    as_deploy_user
    cd "$DIR"
    staging=$(mktemp -d "$DIR/.staging.XXXXXX")
    trap 'rm -rf "$staging"' EXIT
    fetch "$2" "$staging" || die "nothing changed"
    install_files "$staging"
    log "deploy files from $REPO@$2" ;;
  --install-hook)
    [ "$#" = 1 ] || usage
    install_hook ;;
  *)
    [ "$#" = 1 ] || usage
    v="${1#v}"
    valid_version "$v" || usage
    as_deploy_user
    deploy "$v" ;;
esac
