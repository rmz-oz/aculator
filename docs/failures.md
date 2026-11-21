# Backups and failures

What happens when a part of the deployment goes down, and how it comes back. CSE 321 section 4. Issue #32.

The deployment is one web service and one PostgreSQL database on Render's free plan, Frankfurt
([architecture](architecture.png), [decision 5](decisions/0005-branching-and-deploy.md)).

## Backups

The Backup workflow runs every night at 03:00 Istanbul time:

1. `scripts/backup.sh` dumps the Render database with `pg_dump --format=custom` (sessions left out) and writes
   `fingerprint.txt`: for every table and materialized view, the row count and an md5 of all rows in a fixed order.
2. The dump is encrypted with AES256 (`BACKUP_PASSPHRASE` secret), because the repository and its artifacts are public,
   and kept for 30 days as a workflow artifact.
3. A second job restores it into an empty PostgreSQL 16 with `scripts/restore.sh`, which fails if any table's
   fingerprint differs from the one taken at backup time. Then `migrate --check`, a refresh of the materialized views,
   and five class reports and five student profiles must open.

So a backup that cannot be restored shows up the next morning as a red run, not on the day it is needed.

Restore by hand:

```
gh run download --name backup-20261120-<run id> --dir backup/
BACKUP_PASSPHRASE=... scripts/restore.sh backup/aculator-*.dump.gpg "$DATABASE_URL"
```

The tools run in the `postgres:16` image, so only Docker is needed. On a Mac, write `host.docker.internal` instead of
`localhost` in the URL. With the fake data (9,600 grades) a backup takes under a second and a checked restore about one.

Losing at most one day of grades (the time since the last backup) is fine for a demo with fake data. Real grades
would need a smaller gap, see replication below.

## When the web app goes down

- The process crashes: Render restarts the container. Every start runs `migrate` first.
- A new version does not start or fails `/healthz/`: Render keeps the previous version running. The Deploy workflow
  waits for the new commit on `/healthz/` and fails after 5 minutes, so the red run shows it.
- A bad version starts but behaves wrong: redeploy an older image, every commit has one (`ghcr.io/rmz-oz/aculator:sha-<commit>`).
  Across the grade partitioning (#33) see the next section.
- The free plan stops the service after 15 minutes without requests; the next request waits for it to start again.
  Open the site a minute before showing it.

## Partitioning the grades (#33)

Done in two deploys, so the version still running during a deploy can always save grades. Migration 0011 adds each
grade's term, which may be empty, and the code that sets it on every save. Migration 0012 partitions the grade table
by term and fills any term an older version left empty. Merge 0012 only after 0011 is live. 0012 cannot be reversed.

Before merging 0012 (merging to main deploys it):

1. Run the Backup workflow by hand and wait for its restore job to pass.
2. Merge when nobody is entering grades. 0012 locks the grade, enrollment, assessment, offering and term tables for
   about 15 s per 480,000 grades, so every page waits meanwhile; it first waits for imports already running to
   finish, and gives up after a minute. 0011 locks the grade table for about 13 s, and an import that was already
   running when it started is refused with "Grades changed while you were saving" and has to be repeated.

To go back after 0012, redeploy the image of the last commit before it. That version sets the term on every save and
works on the partitioned table, so the partitioning can stay. To undo the partitioning itself, restore the backup from
step 1 with `scripts/restore.sh` after redeploying that image; grades entered since the backup are lost. The
`restore.sh` from before #33 cannot restore over a partitioned database.

## When the database goes down

`/healthz/` runs `SELECT 1`, so it fails and Render marks the service unhealthy; pages answer with an error.

Nothing is half written: a grade import is one SERIALIZABLE transaction (decision 8), so an import is in completely
or not at all. The score views refresh after the transaction commits.

If the data is lost or damaged, restore the newest backup into it. If the database itself is gone, or the free one
expires, `scripts/render_db.sh recreate` creates a new one from the backup (decision 9).

## When Render goes down

The same image runs anywhere with Docker. On a laptop:

```
docker compose up -d db
BACKUP_PASSPHRASE=... scripts/restore.sh backup/aculator-*.dump.gpg postgres://postgres:postgres@host.docker.internal:5432/aculator
docker compose up
```

With `DB_PORT=5433` (README), use port 5433 in the URL. This is also the plan for the demo day if the network fails.

## Replication

The free plan has one database and no replica, so we describe it instead of running it.

PostgreSQL streaming replication: the primary writes every change to its write-ahead log (WAL) first, and a standby
server receives the WAL over a connection and applies it, so it holds a copy that is seconds behind or, with
synchronous replication, not behind at all.

- Failover: when the primary dies, the standby is promoted and the app's `DATABASE_URL` points to it. With
  asynchronous replication the last few transactions can be lost; with synchronous replication a commit waits until
  the standby has the WAL, so nothing is lost, but every write is slower.
- Read replicas: the class reports and student profiles only read, so they could run on a replica and leave the
  primary to grade imports. The materialized views are refreshed on the primary and reach the replica through the
  WAL like any table.
- Point in time recovery: keeping the WAL as well as a nightly base backup allows restoring to any moment, for
  example to one minute before a wrong import, instead of to last night.

For real grades we would use a paid plan with a standby and point in time recovery, and keep the nightly dump as a
second copy outside the provider.
