# aculator

[![CI](https://github.com/rmz-oz/aculator/actions/workflows/ci.yml/badge.svg)](https://github.com/rmz-oz/aculator/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-blue)
![Django](https://img.shields.io/badge/django-5.2-0C4B33)
![PostgreSQL](https://img.shields.io/badge/postgresql-16-336791)

Turns course grades into Learning Outcome and Program Outcome scores for every student, so a department can see
how each graduate meets its program outcomes. Team project for CSE 311 Software Engineering and CSE 321 Data Systems,
Acıbadem University, Fall 2026.

## Team: Django Unchained

- Ramiz Özdemir: lead, architecture
- Yaren Sargın: database
- Esin Sarıaltın: backend and calculation
- Rana İlgi Yılmaz: product owner, frontend

## Presentations

[![Checkpoint 1 slides, overview of the canvas](docs/slides/checkpoint1.png)](https://rmz-oz.github.io/aculator/slides/checkpoint1.html)

[CSE 321 Checkpoint 1, 12 November](https://rmz-oz.github.io/aculator/slides/checkpoint1.html). Arrow keys to move,
O for the overview, N for speaker notes, F for full screen. Built by `python3 docs/slides/build.py`.

## Run locally

```
docker compose up -d
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Settings come from environment variables, see `.env.example`. The defaults match the compose database.

## Deploy

Every green `main` is built into `ghcr.io/rmz-oz/aculator` and deployed to Render, see
[decision 5](docs/decisions/0005-branching-and-deploy.md). To run the image locally:

```
docker build -t aculator . && docker run --rm -p 8000:8000 -e DATABASE_URL=postgres://postgres:postgres@host.docker.internal:5432/aculator aculator
```

## How we work

See [CONTRIBUTING.md](CONTRIBUTING.md). In short: every task is an issue, every change is a pull request reviewed by
a teammate, `main` is always green. Sprints are one week, see the milestones.
