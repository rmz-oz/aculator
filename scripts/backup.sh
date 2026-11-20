#!/bin/sh
# Dump a database to DIR/aculator-<UTC time>.dump plus DIR/fingerprint.txt (#32).
# With BACKUP_PASSPHRASE set, the dump is encrypted to .dump.gpg (AES256) and the
# plain file is removed: the repository is public, so are its workflow artifacts.
#
#   scripts/backup.sh "$DATABASE_URL" backups/
set -eu
url=$1
dir=$2
. "$(dirname "$0")/pg.sh"
mkdir -p "$dir"
name="aculator-$(date -u +%Y%m%d-%H%M).dump"

# Custom format: compressed, and pg_restore can pick tables from it.
pg pg_dump "$url" --format=custom --no-owner --no-acl --exclude-table-data=django_session > "$dir/$name"
fingerprint "$url" > "$dir/fingerprint.txt"

if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  printf %s "$BACKUP_PASSPHRASE" | gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 0 \
    --symmetric --cipher-algo AES256 --output "$dir/$name.gpg" "$dir/$name"
  rm "$dir/$name"
  name="$name.gpg"
fi
echo "$dir/$name, $(wc -c < "$dir/$name" | tr -d ' ') bytes, $(wc -l < "$dir/fingerprint.txt" | tr -d ' ') tables"
