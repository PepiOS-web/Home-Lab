FROM python:3.11-slim AS wheels

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY _upstream/requirements-hardened.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt

FROM python:3.11-slim

RUN groupadd --gid 10001 camera \
    && useradd --uid 10001 --gid camera --no-create-home --shell /usr/sbin/nologin camera

COPY --from=wheels /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels netifaces==0.11.0 \
    && rm -rf /wheels

WORKDIR /app
COPY --chown=camera:camera _upstream/src/ /app/

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD ["python", "-c", "import os,socket; s=socket.create_connection((os.environ.get('A9_HTTP_BIND_HOST','127.0.0.1'),18080),2); s.close()"]

ENTRYPOINT ["python", "-B", "/app/hardened_server.py", "--http-port", "18080"]
