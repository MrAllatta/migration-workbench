# syntax=docker/dockerfile:1
# Stages: `builder` (install app, collectstatic) and `runtime` (Litestream, non-root `app` user).
# App root: /app. Entrypoint: /app/scripts/entrypoint.sh (optional Litestream restore, migrate, then Gunicorn).
#
# Pin: bump `PYTHON_IMAGE_DIGEST` with `docker buildx imagetools inspect python:3.11-slim-bookworm`
# and the digest for the linux/amd64 image you intend to support.
# Pin: `LITESTREAM_VERSION` must match a published benbjohnson/litestream release (linux-amd64 tarball).

ARG PYTHON_IMAGE_DIGEST=sha256:ee710afcfb733f4a750d9be683cf054b5cd247b6c5f5237a6849ea568b90ab15
# Human-readable: docker.io/library/python:3.11-slim-bookworm @ digest above.

FROM python@${PYTHON_IMAGE_DIGEST} AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY manage.py ./
COPY migration_workbench migration_workbench/
COPY connectors connectors/
COPY profiler profiler/
COPY importer importer/
COPY examples examples/
COPY workbook workbook/
COPY deployment deployment/
COPY scripts scripts/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -e .

# Dummy key only for this RUN (not persisted as an image ENV layer).
RUN DJANGO_SECRET_KEY=dummy-build-only-collectstatic DJANGO_DEBUG=0 \
    python manage.py collectstatic --noinput


FROM python@${PYTHON_IMAGE_DIGEST} AS runtime

ARG LITESTREAM_VERSION=v0.3.13
ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/${LITESTREAM_VERSION}/litestream-${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
        | tar -xz -C /usr/local/bin \
    && chmod +x /usr/local/bin/litestream \
    && test "$(/usr/local/bin/litestream version | tr -d '\n')" = "${LITESTREAM_VERSION}" \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app \
    && chmod +x /app/scripts/entrypoint.sh

USER app

WORKDIR /app

# Gunicorn may use a stats/control path under $HOME; the `app` user has no /home entry.
ENV HOME=/tmp

ENV DJANGO_SETTINGS_MODULE=migration_workbench.settings

EXPOSE 8080

CMD ["/app/scripts/entrypoint.sh"]
