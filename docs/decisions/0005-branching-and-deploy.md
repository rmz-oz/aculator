# 5. GitHub Flow, main is what runs

We use GitHub Flow: short branches off `main`, one pull request each, one review, CI green, squash merge. There is no
separate development or release branch. With four people and one week sprints a second long lived branch would only
add merges.

`main` is the deployment branch. When CI passes on `main`, the Deploy workflow builds a Docker image, pushes it to
`ghcr.io/rmz-oz/aculator` tagged with the commit, and tells Render to run that image. Migrations run when the
container starts. Every deployed version can be traced to one commit, and rolling back means redeploying an older
image tag.

At the end of each sprint we tag `main` as `sprint-N`, so the report can point at what each sprint delivered.

Status: proposed, team to confirm. Issue #29.
