FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

# gettext: msgfmt compiles locale/*/LC_MESSAGES/*.po into the .mo files Django
# reads at runtime; .mo is gitignored as a build artifact (#49).
RUN apt-get update && apt-get install -y --no-install-recommends gettext && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The commit this image was built from, reported by /healthz/.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
RUN python manage.py compilemessages
RUN SECRET_KEY=build DEBUG=0 python manage.py collectstatic --noinput

RUN useradd --create-home app
USER app

EXPOSE 8000
CMD ["./start.sh"]
