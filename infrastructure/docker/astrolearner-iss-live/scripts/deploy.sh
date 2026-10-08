#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Ejecuta este script con sudo" >&2
    exit 1
fi

project_dir=/srv/data/compose/astrolearner-iss-live
homepage_dir=/srv/data/compose/homepage

cd "${project_dir}"
docker compose config --quiet
docker compose build --pull iss-live
docker compose up --detach --force-recreate --wait --wait-timeout 240 iss-live

docker exec caddy caddy validate \
    --config /etc/caddy/Caddyfile \
    --adapter caddyfile
docker exec caddy caddy reload \
    --config /etc/caddy/Caddyfile \
    --adapter caddyfile

cd "${homepage_dir}"
docker compose config --quiet
docker compose up --detach --force-recreate --wait --wait-timeout 120

curl --fail --silent --show-error http://127.0.0.1:8092/health
echo
curl --fail --silent --show-error \
    --header "Host: portal.home.arpa" \
    http://127.0.0.1:8080/iss-live/status.json
echo
echo "AstroLearner ISS Live desplegado en modo seguro de simulación."
