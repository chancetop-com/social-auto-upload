#!/bin/sh
set -eu
umask 077
scripts=$(CDPATH= cd -- "$(dirname "$0")" && pwd -P)
root=${1:-"$HOME/Library/Application Support/social-auto-upload"}
mkdir -p -- "$root/state"
root=$(cd -- "$root" && pwd -P)
if [ -f "$root/release-host.sh" ]; then exec "$root/cli-service" start; fi
: "${SAU_DESKTOP_TOKEN:?Set SAU_DESKTOP_TOKEN}"
base=${SAU_GATEWAY_URL:-https://social-media-web-api.connexup-dev.net}
base=${base%/}
export base
/usr/bin/perl -MURI -e '
  $u=URI->new($ENV{base}); $h=$u->host // "";
  die "Invalid Gateway origin\n" unless $h && !$u->userinfo && !defined($u->query) && !defined($u->fragment)
    && ($u->scheme eq "https" || ($u->scheme eq "http" && $h =~ /^(localhost|127\.0\.0\.1|::1)$/));
  die "Invalid bearer\n" if $ENV{SAU_DESKTOP_TOKEN} =~ /[\r\n]/;'
stage=$(/usr/bin/mktemp -d "$root/.approval.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 1' HUP INT TERM
if [ ! -f "$root/state/machine-id" ]; then
    /usr/bin/uuidgen | tr A-F a-f > "$stage/id"
    ln "$stage/id" "$root/state/machine-id" || test -f "$root/state/machine-id"
fi
if [ "$(/usr/bin/uname -m)" = arm64 ] || [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || :)" = 1 ]; then
    target=macos-arm64
else
    target=macos-x86_64
fi
req() {
    if [ -n "${SAU_GATEWAY_CA_FILE:-}" ]; then set -- --cacert "$SAU_GATEWAY_CA_FILE" "$@"; fi
    printf 'Authorization: Bearer %s\n' "$SAU_DESKTOP_TOKEN" | /usr/bin/curl --disable --silent --show-error --fail \
      --noproxy '*' --proto '=http,https' --connect-timeout 10 --max-time 900 -H @- "$@"
}
/usr/bin/perl -MJSON::PP -e '
  sub load_file {local $/; open my $f, "<", $_[0] or die $!; return scalar <$f>}
  ($root,$target)=@ARGV; $id=load_file("$root/state/machine-id"); chomp $id;
  $r={machineId=>$id,target=>$target};
  if (-f "$root/program/package.sha256") {
    $r->{sha256}=load_file("$root/program/package.sha256");
    $r->{revision}=decode_json(load_file("$root/program/release.json"))->{revision};
  } print encode_json($r)' "$root" "$target" > "$stage/request"
req -H 'Content-Type: application/json' --data-binary "@$stage/request" "$base/session/release/discover" -o "$stage/reply"
/usr/bin/perl -MJSON::PP -e '
  local $/; ($target,$stage,$existing)=@ARGV; open my $f,"<","$stage/reply" or die $!;
  my $reply=decode_json(<$f>); my $a=$reply->{assignment} // (!$existing ? $reply->{approved} : undef);
  die "No eligible release yet; retry after the current batch\n" unless $a;
  die "Invalid package source or pin\n" unless $a->{target} eq $target && $a->{revision}=~/^[a-f0-9]{40}\z/ &&
    $a->{sha256}=~/^[a-f0-9]{64}\z/ && $a->{url} eq "/session/release/packages/".$a->{sha256};
  for my $k (qw(revision sha256)) {open my $out,">","$stage/$k" or die $!; print $out $a->{$k};}
  if ($reply->{assignment}) {open my $out,">","$stage/assignment.json" or die $!; print $out encode_json($a)}' \
    "$target" "$stage" "$(test -d "$root/program" && echo 1 || echo 0)"
revision=$(cat "$stage/revision")
digest=$(cat "$stage/sha256")
req "$base/session/release/packages/$digest" -o "$stage/sau-desktop-$revision-$target.zip"
if [ -f "$stage/assignment.json" ]; then export SAU_BOOTSTRAP_ASSIGNMENT="$stage/assignment.json"; fi
"$scripts/bootstrap.sh" "$revision" "$digest" "$stage" "$root"
