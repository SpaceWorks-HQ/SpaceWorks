FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Created before COPY so the source can be chowned as it lands. A later
# `chown -R /app` would instead duplicate the whole tree into a second layer.
RUN useradd --system --create-home --uid 10001 app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# STATIC_ROOT (settings.py: BASE_DIR/"staticfiles") must be writable because the
# container runs `collectstatic` at boot, and CELERY_BEAT_DIR holds beat's schedule
# shelve. Both are runtime state owned by the unprivileged user.
RUN mkdir -p /app/staticfiles /var/lib/celery \
    && chown app:app /app/staticfiles /var/lib/celery

# Drop root. Everything above this line runs privileged; nothing below does.
USER app

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
