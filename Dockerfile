# Pipeline image: Python 3.12 + Playwright's Chromium (for JavaScript-only sources) + supercronic for scheduling.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

# supercronic: cron for containers (logs to stdout, handles signals, no root daemon).
ARG SUPERCRONIC_VERSION=v0.2.33
RUN curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY mock_site/ mock_site/
COPY migrations/ migrations/
# The image's Python is the OS one (PEP 668); inside a container installing into it is fine.
RUN pip install --no-cache-dir --break-system-packages ".[browser,mock-site]" "playwright==1.63.0"

COPY deploy/crontab /app/crontab
RUN useradd --create-home pipeline && mkdir -p /app/data && chown -R pipeline /app/data
USER pipeline

ENV FREIGHT_RAW_DIR=/app/data/raw \
    FREIGHT_REPORT_DIR=/app/data/reports \
    PYTHONUNBUFFERED=1

# Default: migrate the schema, then run on the crontab schedule. Override with e.g. `freight run`.
CMD ["sh", "-c", "freight migrate && exec supercronic /app/crontab"]
