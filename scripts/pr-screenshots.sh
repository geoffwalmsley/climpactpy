#!/bin/sh
# Publish screenshots for a pull request and print the Markdown to paste into its body.
#
#   scripts/pr-screenshots.sh <pr-number> <image>...
#
# GitHub has no API for uploading images to a pull request, so the images go to the orphan
# branch `pr-screenshots`, under pr-<number>/. That branch shares no history with `main`
# and is never merged, so the images never enter `main`. The repository is public, so the
# printed raw.githubusercontent.com links show in the pull request.
set -eu

if [ $# -lt 2 ]; then
    echo "usage: scripts/pr-screenshots.sh <pr-number> <image>..." >&2
    exit 2
fi
pr=$1
shift
for f in "$@"; do
    [ -f "$f" ] || { echo "pr-screenshots: no file $f" >&2; exit 1; }
done

root=$(cd "$(dirname "$0")/.." && pwd)
branch=pr-screenshots
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
tmp=$(mktemp -d)
cleanup() { git -C "$root" worktree remove --force "$tmp" >/dev/null 2>&1 || rm -rf "$tmp"; }
trap cleanup EXIT

if git -C "$root" ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    git -C "$root" fetch -q origin "$branch"
    git -C "$root" worktree add -q --detach "$tmp" "origin/$branch"
else
    git -C "$root" worktree add -q --detach "$tmp"
    git -C "$tmp" checkout -q --orphan "$branch-new"
    git -C "$tmp" rm -rqf .
fi

mkdir -p "$tmp/pr-$pr"
for f in "$@"; do cp "$f" "$tmp/pr-$pr/"; done
git -C "$tmp" add "pr-$pr"
git -C "$tmp" commit -q -m "Screenshots for #$pr"

# Another pull request may have pushed in the meantime: rebase onto it and try again.
tries=0
until git -C "$tmp" push -q origin "HEAD:refs/heads/$branch" 2>/dev/null; do
    tries=$((tries + 1))
    if [ "$tries" -ge 5 ]; then
        echo "pr-screenshots: could not push to $branch" >&2
        exit 1
    fi
    git -C "$tmp" fetch -q origin "$branch"
    git -C "$tmp" rebase -q "origin/$branch"
done

for f in "$@"; do
    name=$(basename "$f")
    echo "![${name%.*}](https://raw.githubusercontent.com/$repo/$branch/pr-$pr/$name)"
done
