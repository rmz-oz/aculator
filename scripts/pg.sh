# Sourced by backup.sh, restore.sh and render_db.sh. PostgreSQL 16 client tools
# from the postgres:16 image, so the version always matches the server: a newer
# pg_dump writes settings that a 16 server rejects on restore.
#
# The container uses the host network (Linux, GitHub Actions). On a Mac,
# localhost inside the container is not the Mac: write host.docker.internal
# instead, e.g. postgres://postgres:postgres@host.docker.internal:5432/aculator.

PG_IMAGE=${PG_IMAGE:-postgres:16}

# stdin is closed, so a tool cannot swallow input meant for the calling script.
pg() {
  docker run --rm --network host -v "$PWD:/work" -w /work "$PG_IMAGE" "$@" < /dev/null
}

pg_stdin() {
  docker run --rm -i --network host -v "$PWD:/work" -w /work "$PG_IMAGE" "$@"
}

# One line per table and materialized view: name, row count, md5 of the rows in
# a fixed order. Two databases with the same fingerprint hold the same data.
# Sessions are left out of backups, so they are left out here too.
fingerprint() {
  url=$1
  # psql runs a backslash command only from a script, not from -c, hence stdin.
  pg_stdin psql "$url" -v ON_ERROR_STOP=1 -AtX -F ' ' <<'SQL'
SELECT format('SELECT %L, count(*), md5(coalesce(string_agg(t::text, %L ORDER BY t::text), %L)) FROM %I t',
              name, '|', '', name)
FROM (SELECT tablename AS name FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'django_session'
      UNION SELECT matviewname FROM pg_matviews WHERE schemaname = 'public') n
ORDER BY name
\gexec
SQL
}
