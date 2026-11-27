#!/bin/sh
set -eu
cd -- "$(dirname "$0")"
versions=.versions
while :; do
    if [ -f "$versions/rollback" ]; then
        if [ -d "$versions/previous" ]; then
            if [ -d program ]; then mv program "$versions/rejected"; fi
            mv "$versions/previous" program
        fi
    elif [ -f "$versions/switch" ]; then
        if [ -d "$versions/next" ]; then
            if [ -d program ]; then mv program "$versions/previous"; fi
            mv "$versions/next" program
        fi
        [ "$(cat program/package.sha256)" = "$(cat "$versions/switch")" ] || exit 1
    fi
    [ "${1:-}" != recover ] || exit 0
    if [ -d "$versions/previous" ] && ! program/runtime/bin/python3.11 -IB -m sau_worker.desktop _probe-install; then
        touch "$versions/rollback"
        continue
    fi
    rc=0
    program/runtime/bin/python3.11 -IB -m sau_worker.desktop _supervise || rc=$?
    [ "$rc" = 75 ] || exit "$rc"
done
