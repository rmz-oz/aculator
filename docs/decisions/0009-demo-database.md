# 9. Demo database: a new free Render database before the old one expires

The free Render PostgreSQL is deleted 30 days after it is created, and a workspace can have one at a time. Ours was
created on 2026-11-03 and expires on 2026-12-03, before the demo on 2026-12-29.

Options:

- A paid Render plan. Nothing expires, but it is a monthly bill for a course project, and the data is fake anyway.
- Another host with a free tier that does not expire. One more account, and every setting changes, for 6 weeks of use.
- A new free Render database. Free, nothing else changes, but the data has to move over and the URL changes.

We take the third one and make the move one command: `scripts/render_db.sh recreate`. It backs up the old database,
deletes it, creates a new one with the same name, restores the backup and compares every table with the backup's
fingerprint, gives the app the new URL, updates the `RENDER_DATABASE_URL` secret for the nightly backup (#32) and
deploys. If the old database cannot be reached any more, it uses the newest nightly backup instead. If there is no
backup at all, the app starts on an empty database and `DEMO=1` loads the fake data.

When: between 2026-12-01 and 2026-12-03. A database created then lives until 2026-12-31 or later, past the demo.
`scripts/render_db.sh status` shows the days left.

Tested end to end against a fake Render API with local databases (one wrong name typed, one full run); backup and
restore are tested every night by the Backup workflow.

Status: proposed, team to confirm. Issue #82.
