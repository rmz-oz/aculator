# Contributing

## Flow (GitHub Flow)

1. Pick an issue from the project board, assign yourself.
2. Branch from `main`: `feat/12-grade-import`, `fix/31-rounding` (type, issue number, short name).
3. Commit from your own account. Small commits, one idea each.
4. Open a pull request early as a draft. Write `Closes #12` in the description so the issue closes on merge.
5. One teammate reviews. CI must pass. Squash and merge, delete the branch.

## Pairing

When two of us write code together, the person typing adds the other as co-author in the commit message, last line:

```
Co-authored-by: Name Surname <their-github-email@example.com>
```

Use the email that GitHub shows on the partner's profile settings, otherwise the commit is not linked to them.

## Questions and decisions

Design questions go to Discussions (Q&A category), not chat. When an answer settles it, mark it as the answer. Decisions
we keep (database, rounding rule, deployment) also get a short note in `docs/decisions/`.

## Reviews

Review within a day. Comment on what the code does, ask instead of telling, approve when it is good enough to merge.
