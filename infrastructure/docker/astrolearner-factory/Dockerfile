FROM python:3.12-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" astro \
    && useradd --uid "${APP_UID}" --gid astro --create-home --shell /usr/sbin/nologin astro

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --requirement /tmp/requirements.txt

COPY --chown=astro:astro app /app/app

USER astro

EXPOSE 8090

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
