FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The commit this image was built from, reported by /healthz/.
ARG GIT_SHA=dev
ENV GIT_SHA=$GIT_SHA
RUN SECRET_KEY=build DEBUG=0 python manage.py collectstatic --noinput

RUN useradd --create-home app
USER app

EXPOSE 8000
# Free Render plans have no pre-deploy step, so migrations run on start.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2"]
