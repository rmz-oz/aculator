#!/bin/sh
# Container start: Render's free plan has no pre-deploy step, so migrations run here.
set -e
python manage.py migrate --noinput
# Demo deployment and docker compose: fake data on an empty database, and the
# three demo accounts (#46). A restored backup keeps its own data.
if [ "$DEMO" = "1" ]; then
  python manage.py demo_data --if-empty
fi
exec gunicorn config.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 2
