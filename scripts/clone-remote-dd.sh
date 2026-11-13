#!/usr/bin/env bash
# clone-remote-dd.sh — safe manual wrapper for remote dd clone with progress.
# Usage: ./clone-remote-dd.sh <remote-host> <source-dev> <local-target-dev> [user]
set +e

REMOTE="${1:-}"; SRC="${2:-}"; DST="${3:-}"; USER_AT="${4:-$USER}"
if [ -z "$REMOTE" ] || [ -z "$SRC" ] || [ -z "$DST" ]; then
  echo "usage: $0 <remote-host> <source-dev> <local-target-dev> [user]"
  echo "example: $0 192.168.1.50 /dev/sda /dev/sdb alice"
  exit 0
fi

say() { printf '%s\n' "$*"; }

say "=== remote dd clone (manual) ==="
say "remote : ${USER_AT}@${REMOTE}"
say "source : ${SRC}"
say "target : ${DST}"
say ""

say "--- local target details ---"
lsblk -o NAME,SIZE,TYPE,MODEL,TRAN "$DST" 2>&1 || say "lsblk could not read $DST"
say ""

say "--- target mount state ---"
for p in "$DST"*; do
  [ -e "$p" ] || continue
  if findmnt -n "$p" >/dev/null; then
    say "MOUNTED: $p — attempting umount"
    sudo umount "$p" || say "umount failed for $p — check: lsof $p"
  fi
done
if mount | grep -q " $DST"; then
  say "WARNING: something under $DST is still mounted — do not proceed"
else
  say "nothing mounted from $DST"
fi
say ""

say "--- remote sudo test ---"
if ! ssh "${USER_AT}@${REMOTE}" "sudo -n true" >/dev/null 2>&1; then
  say "WARNING: passwordless sudo not available on ${REMOTE}."
fi

say "--- source size ---"
SRC_BYTES=$(ssh "${USER_AT}@${REMOTE}" "sudo blockdev --getsize64 ${SRC}" 2>&1)
case "$SRC_BYTES" in
  ''|*[!0-9]*) say "could not read source size: $SRC_BYTES"; SRC_BYTES="" ;;
  *) say "source bytes: $SRC_BYTES" ;;
esac

say ""
say "--- command that will run ---"
if command -v pv >/dev/null; then
  say "ssh ${USER_AT}@${REMOTE} \"sudo dd if=${SRC} bs=4M status=progress\" \\"
  say "  | pv -s ${SRC_BYTES:-0} -b -t -r -e \\"
  say "  | sudo dd of=${DST} bs=4M status=progress conv=fsync"
else
  say "ssh ${USER_AT}@${REMOTE} \"sudo dd if=${SRC} bs=4M status=progress\" \\"
  say "  | sudo dd of=${DST} bs=4M status=progress conv=fsync"
  say ""
  say "pv not found; using dd status=progress only."
fi

say ""
printf 'Type the target device (%s) again to confirm: ' "$DST"
read -r CONFIRM
if [ "$CONFIRM" != "$DST" ]; then
  say "confirmation did not match; aborting without writing."
  exit 0
fi

say "--- starting ---"
if command -v pv >/dev/null && [ -n "$SRC_BYTES" ]; then
  ssh "${USER_AT}@${REMOTE}" "sudo dd if=${SRC} bs=4M status=progress" \
    | pv -s "$SRC_BYTES" -b -t -r -e \
    | sudo dd of="$DST" bs=4M status=progress conv=fsync
else
  ssh "${USER_AT}@${REMOTE}" "sudo dd if=${SRC} bs=4M status=progress" \
    | sudo dd of="$DST" bs=4M status=progress conv=fsync
fi
RC=$?
say ""
say "dd pipeline exit code: $RC"
say "run sync and verify the first/last MiB before unplugging."
