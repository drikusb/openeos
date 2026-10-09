FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user rather than root. uid/gid 1000 is the first
# regular user on most Linux hosts, so a bind-mounted checkout (see
# docker-compose.yml) keeps the same owner inside and outside the container.
# The chown runs after COPY so that /app/staticfiles and /app/mediafiles are
# owned by this user in the image: the named volumes in docker-compose.prod.yml
# copy that ownership when they are first created.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/staticfiles /app/mediafiles \
    && chown -R app:app /app \
    && chmod +x /app/entrypoint.sh

EXPOSE 8000

USER app
