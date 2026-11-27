#!/bin/sh
# Usage: bootstrap.sh REVISION SHA256 ARTIFACT_DIR [INSTALL_ROOT]
set -eu
umask 077
test "$(/usr/bin/uname -s)" = Darwin || { echo "Requires macOS" >&2; exit 1; }
# Report hardware even when Terminal runs under Rosetta.
if [ "$(/usr/bin/uname -m)" = arm64 ] || [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || :)" = 1 ]; then
    target=macos-arm64
else
    target=macos-x86_64
fi

install_pinned() (
    set -e
    test "$#" -ge 3 && test "$#" -le 4 || { echo "Expected REVISION SHA256 ARTIFACT_DIR [INSTALL_ROOT]" >&2; exit 2; }
    revision=$1
    digest=$2
    case "$revision$digest" in *[!0-9a-f]*) echo "Expected lowercase hex pins" >&2; exit 2;; esac
    test "${#revision}" = 40 && test "${#digest}" = 64 || { echo "Invalid pin length" >&2; exit 2; }
    root=${4:-"$HOME/Library/Application Support/social-auto-upload"}
    mkdir -p -- "$root"
    root=$(cd -- "$root" && pwd -P)
    stage=$(/usr/bin/mktemp -d "$root/.bootstrap.XXXXXXXX")
    trap 'rm -rf -- "$stage"' EXIT
    trap 'exit 1' HUP INT TERM
    cp -- "$3/sau-desktop-$revision-$target.zip" "$stage/package.zip"
    actual=$(/usr/bin/shasum -a 256 < "$stage/package.zip")
    test "${actual%% *}" = "$digest" || { echo "Package SHA-256 mismatch" >&2; exit 1; }
    mkdir "$stage/image"
    # Inspect every member before allowing the first write. Never create links.
    # macOS supplies Archive::Zip with its system Perl.
    cd -- "$stage/image"
    /usr/bin/perl -MArchive::Zip=:ERROR_CODES -MFile::Path=make_path -MFile::Basename=dirname -e '
      use strict; use warnings;
      my $zip = Archive::Zip->new();
      $zip->read($ARGV[0]) == AZ_OK or die "Cannot read package\n";
      my (%files, %dirs);
      for my $m ($zip->members) {
        my $n = $m->fileName;
        die "Unsafe package member\n" unless $n eq "release.json" || $n =~ m{^runtime/};
        die "Unsafe package member\n" unless (($m->externalFileAttributes >> 16) & 0170000) == 0100000;
        my @parts = split m{/}, $n, -1;
        my $prefix = "";
        for my $p (@parts) {
          die "Unsafe package member\n" if $p eq "" || $p =~ /[. ]$/ || $p =~ /[\x00-\x1f\x7f\\:<>|"*?]/ ||
            $p =~ /^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i;
          $prefix .= ($prefix eq "" ? "" : "/") . lc($p);
          die "Unsafe package member\n" if $files{$prefix};
          $dirs{$prefix} = 1 if $prefix ne lc($n);
        }
        die "Unsafe package member\n" if $dirs{$prefix};
        $files{$prefix} = 1;
      }
      for my $m ($zip->members) {
        my $n = $m->fileName; make_path(dirname($n));
        $m->extractToFileNamed($n) == AZ_OK or die "Incomplete package\n";
        chmod(($m->unixFileAttributes & 0111) ? 0755 : 0644, $n) or die "chmod: $!";
      }
    ' "$stage/package.zip"
    if [ -n "${SAU_BOOTSTRAP_ASSIGNMENT:-}" ]; then
        "$stage/image/runtime/bin/python3.11" -IB -m sau_worker.desktop _verify "$revision" "$target" || exit 65
    fi
    export SAU_VERIFIED_ARCHIVE="$stage/package.zip"
    "$stage/image/runtime/bin/python3.11" -I -B -m sau_worker.desktop install "$root" "$revision" "$digest" "$target"
)

if [ "$#" = 0 ] || [ "${1:-}" = --approved ]; then
    [ "$#" -le 2 ] || exit 2
    if [ "$#" -gt 0 ]; then shift; fi
    . "$(dirname "$0")/approved.sh"
    exit $?
fi
install_pinned "$@"
