#!/bin/sh
# Restore a backup from scripts/backup.sh into a database, replacing what is
# there, then check it against the fingerprint taken at backup time (#32).
#
#   scripts/restore.sh backups/aculator-20261120-0000.dump.gpg "$DATABASE_URL"
#
# An encrypted file needs BACKUP_PASSPHRASE. Exits non-zero if any table differs.
set -eu
file=$1
url=$2
. "$(dirname "$0")/pg.sh"
work=$(mktemp -d "$PWD/.restore.XXXXXX")
trap 'rm -rf "$work"' EXIT

case "$file" in
  *.gpg)
    printf %s "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE is needed for $file}" \
      | gpg --batch --quiet --pinentry-mode loopback --passphrase-fd 0 --decrypt --output "$work/backup.dump" "$file"
    ;;
  *) cp "$file" "$work/backup.dump" ;;
esac

# --clean drops each object before creating it, so the target may hold an older copy.
pg pg_restore --dbname="$url" --clean --if-exists --no-owner --no-acl --exit-on-error \
  "$(basename "$work")/backup.dump"
echo "restored $file"

expected="$(dirname "$file")/fingerprint.txt"
if [ -f "$expected" ]; then
  fingerprint "$url" > "$work/after.txt"
  if diff "$expected" "$work/after.txt"; then
    echo "same data as at backup time: $(wc -l < "$expected" | tr -d ' ') tables and views"
  else
    echo "restored data differs from the backup's fingerprint" >&2
    exit 1
  fi
fi
