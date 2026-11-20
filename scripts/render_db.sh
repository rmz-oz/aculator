#!/bin/sh
# The demo database on Render (#82, decision 0009). A free Render database
# lives 30 days and a workspace may have one, so it is replaced, not renewed.
#
#   scripts/render_db.sh status      name, state and days left
#   scripts/render_db.sh open        allow connections from outside Render (password and TLS)
#   scripts/render_db.sh recreate    back up, delete, create, restore, point the app at it
#   scripts/render_db.sh recreate FILE   the same from a backup file, e.g. after a failed run
#
# Needs: a Render API key in RENDER_API_KEY or ~/.render_api_key, docker,
# jq, gpg, and gh signed in to the repository (for the backup secret and artifacts).
set -eu
cd "$(dirname "$0")/.."
. scripts/pg.sh

DB_NAME=aculator-db
SERVICE_NAME=aculator
API=${RENDER_API:-https://api.render.com/v1}
KEY=${RENDER_API_KEY:-$(cat ~/.render_api_key)}
ALLOW='[{"cidrBlock":"0.0.0.0/0","description":"everywhere, password and TLS"}]'

api() { # method path [json body]
  if [ $# -ge 3 ]; then
    curl -fsS -X "$1" -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d "$3" "$API$2"
  else
    curl -fsS -X "$1" -H "Authorization: Bearer $KEY" -H "Accept: application/json" "$API$2"
  fi
}
db_json() { api GET "/postgres?name=$DB_NAME" | jq '.[0].postgres // empty'; }
service_id() { api GET "/services?name=$SERVICE_NAME" | jq -r '.[0].service.id'; }
external_url() { api GET "/postgres/$1/connection-info" | jq -r .externalConnectionString; }
internal_url() { api GET "/postgres/$1/connection-info" | jq -r .internalConnectionString; }

status() {
  db=$(db_json)
  [ -n "$db" ] || { echo "no database named $DB_NAME"; return; }
  echo "$db" | jq -r '"\(.name) \(.id) \(.status), plan \(.plan), expires \(.expiresAt // "never")"'
  expires=$(echo "$db" | jq -r '.expiresAt // empty' | cut -c1-19)
  if [ -n "$expires" ]; then
    left=$(( ($(date -u -j -f %Y-%m-%dT%H:%M:%S "$expires" +%s 2>/dev/null || date -u -d "$expires" +%s) - $(date +%s)) / 86400 ))
    echo "$left days left"
  fi
}

open_external() {
  id=$(db_json | jq -r .id)
  api PATCH "/postgres/$id" "{\"ipAllowList\":$ALLOW}" | jq -c .ipAllowList
}

# Newest nightly backup from the Backup workflow, for when the old database is
# already unreachable.
latest_artifact() {
  name=$(gh api "repos/{owner}/{repo}/actions/artifacts?per_page=100" \
    --jq '[.artifacts[] | select(.name | startswith("backup-")) | select(.expired | not)] | sort_by(.created_at) | last | .name')
  [ -n "$name" ] || { echo "no backup artifact" >&2; return 1; }
  gh run download --name "$name" --dir "$1" >&2
  echo "using artifact $name" >&2
}

recreate() {
  : "${BACKUP_PASSPHRASE:?set BACKUP_PASSPHRASE, the same as the repository secret}"
  old=$(db_json)
  service=$(service_id)
  dir="backups/$(date -u +%Y%m%d-%H%M)"

  # 1. A backup of the old database, or the newest nightly one if it cannot be reached.
  if [ -n "${1:-}" ]; then
    file=$1
  else
    if [ -n "$old" ] && sh scripts/backup.sh "$(external_url "$(echo "$old" | jq -r .id)")" "$dir"; then
      :
    else
      rm -rf "$dir"; mkdir -p "$dir"
      latest_artifact "$dir"
    fi
    file=$(ls "$dir"/*.dump.gpg)
  fi
  echo "backup: $file"

  # 2. One free database per workspace: the old one has to go first.
  if [ -n "$old" ]; then
    old_id=$(echo "$old" | jq -r .id)
    owner=$(echo "$old" | jq -r .owner.id)
    printf 'Delete %s (%s) and create a new one? Type the name to go on: ' "$DB_NAME" "$old_id"
    read -r answer
    [ "$answer" = "$DB_NAME" ] || { echo "stopped, nothing changed"; exit 1; }
    api DELETE "/postgres/$old_id" > /dev/null
    while [ -n "$(db_json)" ]; do sleep 5; done
    echo "deleted $old_id"
  else
    owner=$(api GET "/owners" | jq -r '.[0].owner.id')
  fi

  # 3. New database, same name and version, reachable from GitHub Actions for backups.
  new_id=$(api POST /postgres "{\"name\":\"$DB_NAME\",\"ownerId\":\"$owner\",\"plan\":\"free\",\"region\":\"frankfurt\",
    \"version\":\"16\",\"databaseName\":\"aculator\",\"databaseUser\":\"aculator\",\"ipAllowList\":$ALLOW}" | jq -r .id)
  echo "creating $new_id"
  until [ "$(api GET "/postgres/$new_id" | jq -r .status)" = available ]; do sleep 10; done
  # The hostname answers a little after the status says available.
  until pg pg_isready -d "$(external_url "$new_id")" -t 5 > /dev/null; do sleep 5; done

  # 4. Restore, checked against the backup's fingerprint.
  sh scripts/restore.sh "$file" "$(external_url "$new_id")"

  # 5. The app and the nightly backup use the new database.
  api PUT "/services/$service/env-vars/DATABASE_URL" "{\"value\":\"$(internal_url "$new_id")\"}" > /dev/null
  api PUT "/services/$service/env-vars/DEMO" '{"value":"1"}' > /dev/null
  external_url "$new_id" | gh secret set RENDER_DATABASE_URL
  deploy=$(api POST "/services/$service/deploys" '{}' | jq -r .id)
  echo "deploying $deploy"
  while :; do
    state=$(api GET "/services/$service/deploys/$deploy" | jq -r .status)
    case "$state" in
      live) break ;;
      *failed|canceled|deactivated) echo "deploy $state" >&2; exit 1 ;;
    esac
    sleep 10
  done
  url=$(api GET "/services/$service" | jq -r .serviceDetails.url)
  curl -fsS "$url/healthz/"; echo
  status
}

case "${1:-}" in
  status) status ;;
  open) open_external ;;
  recreate) recreate "${2:-}" ;;
  *) sed -n '2,11p' "$0"; exit 1 ;;
esac
