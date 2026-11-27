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
            if [ -d program ]; then test ! -e "$versions/previous"; mv program "$versions/previous"; fi
            mv "$versions/next" program
        fi
        if [ ! -f program/package.sha256 ] || [ "$(cat program/package.sha256)" != "$(cat "$versions/switch")" ]; then
            [ -d "$versions/previous" ] || [ -f program/package.sha256 ] || exit 1
            touch "$versions/repair" "$versions/rollback"
            continue
        fi
    fi
    [ "${1:-}" != recover ] || exit 0
    if [ -f state/disabled ] || [ -f state/uninstalled ]; then exit 0; fi
    if [ -d "$versions/previous" ] && ! "$versions/previous/runtime/bin/python3.11" -IB verify-install.py; then
        touch "$versions/repair" "$versions/rollback"
        continue
    fi
    if [ -d "$versions/previous" ] && ! program/runtime/bin/python3.11 -IB -m sau_worker.desktop _probe-install; then
        touch "$versions/rollback"
        continue
    fi
    rc=0
    program/runtime/bin/python3.11 -IB -m sau_worker.desktop _supervise || rc=$?
    [ "$rc" = 75 ] || exit "$rc"
done
