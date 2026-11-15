#!/usr/bin/env bash
# Build, smoke-test, scan, tag and push the climpact-web image (#122). The CI workflow
# (pull requests and main) and the release workflow both run these steps, so what a pull
# request tests is what a release publishes. See TECHNICAL.md › Deployment › "Image in CI".
#
#   scripts/image.sh build <image>                  linux/amd64 build, loaded into Docker
#   scripts/image.sh smoke <image>                  run it against Postgres (see below)
#   scripts/image.sh scan <image>                   Grype report; never fails the build
#   scripts/image.sh tags <git tag> <prerelease>    the registry tags for a release
#   scripts/image.sh tags-selftest                  check `tags` on fixed cases
#   scripts/image.sh publish <image> <repo> <tag>.. tag and push (needs `docker login`)
#
# build: BUILDX_CACHE_FROM / BUILDX_CACHE_TO name local cache folders (a docker-container
# buildx builder is needed to export the cache); IMAGE_VERSION and IMAGE_REVISION become
# OCI labels.
# smoke: SMOKE_NETWORK is a Docker network on which SMOKE_DATABASE_URL reaches an empty
# Postgres database (in CI the job's service network and `postgres` host).
set -euo pipefail

cd "$(dirname "$0")/.."

# Grype, from its official image, pinned by the digest of the multi-platform index of the
# tag in the comment. Upgrade the tag and digest together in a deliberate pull request.
GRYPE_IMAGE=anchore/grype:v0.121.0@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea

die() { echo "error: $*" >&2; exit 1; }

cmd_build() {
    local image=${1:?image name}
    local args=(--platform linux/amd64 --provenance=false --sbom=false --load -t "$image")
    [ -n "${BUILDX_CACHE_FROM:-}" ] && args+=(--cache-from "type=local,src=$BUILDX_CACHE_FROM")
    [ -n "${BUILDX_CACHE_TO:-}" ] && args+=(--cache-to "type=local,dest=$BUILDX_CACHE_TO,mode=max")
    [ -n "${IMAGE_VERSION:-}" ] && args+=(--label "org.opencontainers.image.version=$IMAGE_VERSION")
    [ -n "${IMAGE_REVISION:-}" ] && args+=(--label "org.opencontainers.image.revision=$IMAGE_REVISION")
    docker buildx build "${args[@]}" .
    docker image ls "$image"
}

cmd_smoke() {
    local image=${1:?image name}
    : "${SMOKE_NETWORK:?SMOKE_NETWORK must name the Docker network of the database}"
    : "${SMOKE_DATABASE_URL:?SMOKE_DATABASE_URL must be the database URL on that network}"
    # Globals, not locals: the EXIT trap runs after this function has returned.
    web=climpact-smoke-web volume=climpact-smoke-media
    local port=${SMOKE_PORT:-8000}
    # As deployed: read-only root, a tmpfs at /tmp, the media volume, the hosted variables.
    local run=(--platform linux/amd64 --network "$SMOKE_NETWORK" --read-only --tmpfs /tmp
        -v "$volume:/var/lib/climpact/media"
        -e CLIMPACT_WEB_SECRET_KEY=smoke-test-only-not-a-secret-0123456789abcdefghijklmnop
        -e CLIMPACT_WEB_ALLOWED_HOSTS=localhost
        -e CLIMPACT_WEB_CSRF_TRUSTED_ORIGINS=https://localhost
        -e "DATABASE_URL=$SMOKE_DATABASE_URL")

    # shellcheck disable=SC2317  # called by the EXIT trap
    cleanup() {
        local status=$?
        if [ "$status" -ne 0 ] && docker container inspect "$web" >/dev/null 2>&1; then
            echo "--- web container log ---"; docker logs "$web" 2>&1 | tail -n 100
        fi
        docker rm -f "$web" >/dev/null 2>&1 || true
        docker volume rm "$volume" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT
    docker rm -f "$web" >/dev/null 2>&1 || true
    docker volume rm "$volume" >/dev/null 2>&1 || true

    echo "::group::migrate, check --deploy"
    docker run --rm "${run[@]}" "$image" migrate
    docker run --rm "${run[@]}" "$image" manage check --deploy --fail-level ERROR
    echo "::endgroup::"

    echo "::group::web: /healthz, the landing page, Docker's health check"
    docker run -d --name "$web" -p "127.0.0.1:$port:8000" "${run[@]}" "$image" web >/dev/null
    local body=""
    for _ in $(seq 60); do
        body=$(curl -fsS -H "Host: localhost" "http://127.0.0.1:$port/healthz" 2>/dev/null) && break
        [ "$(docker inspect -f '{{.State.Running}}' "$web")" = true ] || die "web exited"
        sleep 1
    done
    echo "/healthz: $body"
    [ "$(jq -r .database <<<"$body")" = ok ] || die "/healthz did not report the database ok"
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' -H "Host: localhost" \
        -H "X-Forwarded-Proto: https" "http://127.0.0.1:$port/")
    [ "$code" = 200 ] || die "landing page behind the proxy: HTTP $code, expected 200"
    code=$(curl -sS -o /dev/null -w '%{http_code}' -H "Host: localhost" "http://127.0.0.1:$port/")
    [ "$code" = 301 ] || die "plain HTTP: HTTP $code, expected a 301 to HTTPS"
    [ "$(docker exec "$web" id -u)" = 10001 ] || die "web does not run as uid 10001"
    if docker exec "$web" sh -c 'touch /opt/climpact/x' 2>/dev/null; then
        die "the root filesystem is writable"
    fi
    local health=""
    for _ in $(seq 90); do
        health=$(docker inspect -f '{{.State.Health.Status}}' "$web")
        [ "$health" = healthy ] && break
        sleep 1
    done
    echo "Docker health: $health"
    [ "$health" = healthy ] || die "Docker's HEALTHCHECK did not report healthy"
    echo "::endgroup::"

    echo "::group::worker: the Sydney sample station run (zip)"
    docker run --rm "${run[@]}" "$image" manage shell -c "
import gzip, shutil
from pathlib import Path
import climpact_web.stations
from climpact_web.jobs.models import Job
sample = Path(climpact_web.stations.__file__).parent / 'sample_data' / 'sydney_observatory_hill_1936-2015.txt.gz'
job = Job.objects.create(kind='station', owner='smoke', params={
    'station_file': 'station.txt',
    'metadata': {'name': 'sydney', 'latitude': -33.86, 'base_start': 1961, 'base_end': 1990},
    'zip': True})
job.input_dir.mkdir(parents=True)
with gzip.open(sample, 'rb') as src, open(job.input_dir / 'station.txt', 'wb') as dst:
    shutil.copyfileobj(src, dst)
"
    docker run --rm "${run[@]}" "$image" worker --once
    docker run --rm "${run[@]}" "$image" manage shell -c "
from climpact_web.jobs.models import Job
job = Job.objects.get(owner='smoke')
print(job.status, job.step, job.total, job.result.get('zip'))
assert job.status == 'succeeded' and job.step == job.total, job.log
"
    echo "::endgroup::"

    docker stop "$web" >/dev/null
    code=$(docker inspect -f '{{.State.ExitCode}}' "$web")
    [ "$code" = 0 ] || die "web exited with status $code on docker stop"
    echo "smoke test passed"
}

cmd_scan() {
    local image=${1:?image name}
    local out
    out=$(mktemp -d)
    docker save "$image" -o "$out/image.tar"
    # Reports only; a finding never fails the build (yet). The table goes to the log, the
    # counts to the job summary.
    if ! docker run --rm -v "$out:/scan" "$GRYPE_IMAGE" "docker-archive:/scan/image.tar" \
        --by-cve -o table -o json=/scan/grype.json; then
        echo "::warning title=Image scan::Grype did not run; no vulnerability report"
        rm -rf "$out"; return 0
    fi
    local counts critical
    counts=$(jq -r '[.matches[].vulnerability.severity] | group_by(.) | map("\(.[0]): \(length)") | join(", ")' "$out/grype.json")
    critical=$(jq '[.matches[] | select(.vulnerability.severity == "Critical")] | length' "$out/grype.json")
    echo "Vulnerabilities: ${counts:-none}"
    if [ "$critical" -gt 0 ]; then
        echo "::warning title=Image scan::$critical critical vulnerabilities (Grype); see the log"
        jq -r '.matches[] | select(.vulnerability.severity == "Critical")
            | "  \(.vulnerability.id)  \(.artifact.name) \(.artifact.version)  fixed in: \(.vulnerability.fix.versions | join(", ") | if . == "" then "-" else . end)"' \
            "$out/grype.json"
    fi
    if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
        {
            echo "### Image scan (Grype)"
            echo
            echo "Vulnerabilities by severity: ${counts:-none}. Critical: **$critical**."
            echo "Reported only; the build does not fail on findings yet."
            if [ "$critical" -gt 0 ]; then
                echo
                echo "| CVE | Package | Version | Fixed in |"
                echo "| --- | --- | --- | --- |"
                jq -r '.matches[] | select(.vulnerability.severity == "Critical")
                    | "| \(.vulnerability.id) | \(.artifact.name) | \(.artifact.version) | \(.vulnerability.fix.versions | join(", ")) |"' \
                    "$out/grype.json"
            fi
        } >>"$GITHUB_STEP_SUMMARY"
    fi
    rm -rf "$out"
}

# The registry tags for a release: the version without the "v", and `latest` only for a
# final release (not marked pre-release on GitHub and without an a/b/rc suffix), so a
# pre-release never becomes what `latest` deploys.
cmd_tags() {
    local tag=${1:?git tag} prerelease=${2:?prerelease true or false}
    [[ "$prerelease" =~ ^(true|false)$ ]] || die "prerelease must be true or false, not '$prerelease'"
    [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)((a|b|rc)[0-9]+)?$ ]] \
        || die "release tag '$tag' is not vX.Y.Z or vX.Y.Z{a,b,rc}N"
    echo "${tag#v}"
    if [ "$prerelease" = false ] && [ -z "${BASH_REMATCH[2]}" ]; then
        echo latest
    fi
}

cmd_tags_selftest() {
    local failed=0 got
    check() {  # check <expected, space-separated or ERROR> <tag> <prerelease>
        if got=$(cmd_tags "$2" "$3" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'); then :; else got=ERROR; fi
        if [ "$got" = "$1" ]; then echo "ok    $2 prerelease=$3 -> $got"
        else echo "FAIL  $2 prerelease=$3 -> '$got', expected '$1'"; failed=1; fi
    }
    check "0.1.0 latest" v0.1.0 false
    check "12.3.45 latest" v12.3.45 false
    check "0.1.0" v0.1.0 true
    check "0.2.0rc1" v0.2.0rc1 true
    check "0.2.0rc1" v0.2.0rc1 false
    check "1.0.0a2" v1.0.0a2 true
    check "1.0.0b1" v1.0.0b1 false
    check ERROR 0.1.0 false
    check ERROR v0.1 false
    check ERROR v0.1.0-rc1 true
    check ERROR v0.1.0.post1 false
    check ERROR "v0.1.0 " false
    check ERROR latest false
    check ERROR v0.1.0 yes
    return "$failed"
}

cmd_publish() {
    local image=${1:?local image} repo=${2:?registry repository}
    shift 2
    [ "$#" -gt 0 ] || die "no tags to push"
    local tag
    for tag in "$@"; do
        docker tag "$image" "$repo:$tag"
        docker push "$repo:$tag"
    done
}

case "${1:-}" in
    build | smoke | scan | tags | publish) c=$1; shift; "cmd_$c" "$@" ;;
    tags-selftest) cmd_tags_selftest ;;
    *) sed -n '2,11p' "$0" >&2; exit 2 ;;
esac
