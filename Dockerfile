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
CMD ["./start.sh"]
