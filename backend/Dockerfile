FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG POSTGRESQL_CLIENT_MAJOR=17
ARG POSTGRESQL_LOCAL_SERVER_MAJOR=16
# Two client majors, because the two directions have opposite constraints:
#   * pg_dump must be at least as new as every supported *source* server (14-17), so
#     POSTGRESQL_CLIENT_MAJOR is what lands on PATH for tenant migration.
#   * pg_restore must be no newer than the *target* server. pg_restore 17+ emits an
#     unconditional `SET transaction_timeout = 0;`, a GUC that does not exist before
#     17, so restoring into the deployment's own postgres:16 with --exit-on-error
#     dies on the preamble. The readable-main projection restores into a temporary
#     database on that server, so it needs a client of the server's own major and
#     resolves it from /usr/lib/postgresql/<major>/bin explicitly.
# Both are versioned package names, so nothing floats to 18. `age` is the archive
# boundary.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg age \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      "postgresql-client-$POSTGRESQL_CLIENT_MAJOR" \
      "postgresql-client-$POSTGRESQL_LOCAL_SERVER_MAJOR" \
    && rm -rf /var/lib/apt/lists/*

# Created before COPY so the source can be chowned as it lands. A later
# `chown -R /app` would instead duplicate the whole tree into a second layer.
RUN useradd --system --create-home --uid 10001 app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

ARG BUILD_GIT_SHA=unknown
ARG BUILD_GIT_DESCRIBE=unknown
RUN BUILD_GIT_SHA="$BUILD_GIT_SHA" BUILD_GIT_DESCRIBE="$BUILD_GIT_DESCRIBE" \
    python /app/scripts/write_build_info.py \
    && chown app:app /app/BUILD_INFO.json

# STATIC_ROOT (settings.py: BASE_DIR/"staticfiles") must be writable because the
# container runs `collectstatic` at boot, and CELERY_BEAT_DIR holds beat's schedule
# shelve. Both are runtime state owned by the unprivileged user.
RUN mkdir -p /app/staticfiles /var/lib/celery /var/lib/spaceworks/ops \
    && chown app:app /app/staticfiles /var/lib/celery /var/lib/spaceworks/ops

# Drop root. Everything above this line runs privileged; nothing below does.
USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
