#!/bin/sh
# Pulls the generated dashboard (branch gh-pages) into the web root.
# Run as the web user from cron every few minutes. Safe to run repeatedly.
set -eu

REPO="${NTR_REPO:-https://github.com/agnstrv/NTR_AI.git}"
ROOT="${NTR_ROOT:-/var/www/ntr-dashboard}"

if [ ! -d "$ROOT/.git" ]; then
  git clone --quiet --depth 1 --single-branch --branch gh-pages "$REPO" "$ROOT"
  exit 0
fi

cd "$ROOT"
git fetch --quiet --depth 1 origin gh-pages
git reset --quiet --hard FETCH_HEAD
