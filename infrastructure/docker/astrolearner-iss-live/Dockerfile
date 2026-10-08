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
        intel-media-va-driver \
        libva-drm2 \
        vainfo \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" isslive \
    && useradd --uid "${APP_UID}" --gid isslive --create-home --shell /usr/sbin/nologin isslive \
    && mkdir -p /data/music /data/nasa /data/secrets /status \
    && chown -R isslive:isslive /data /status

WORKDIR /app

COPY requirements.lock /tmp/requirements.lock
RUN pip install --require-hashes --requirement /tmp/requirements.lock

COPY --chown=isslive:isslive app /app/app

USER isslive

EXPOSE 8092

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app"]
