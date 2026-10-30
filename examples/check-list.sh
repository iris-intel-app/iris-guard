#!/usr/bin/env bash
# The CLI in a script: keep only the mints iris-guard allows.
#   ./check-list.sh mints.txt > allowed.txt
while read -r mint; do
  [ -z "$mint" ] && continue
  if npx --yes iris-guard "$mint" >&2; then echo "$mint"; fi
done < "${1:-/dev/stdin}"
