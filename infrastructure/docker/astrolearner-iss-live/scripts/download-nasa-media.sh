#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
    echo "Ejecuta este script con sudo" >&2
    exit 1
fi

project_dir=/srv/data/compose/astrolearner-iss-live
cd "${project_dir}"
if ! grep --quiet '^ISS_LIVE_DRY_RUN=true$' .env; then
    echo "La descarga solo se permite con ISS_LIVE_DRY_RUN=true" >&2
    exit 1
fi
docker compose build iss-live
docker compose run --rm --no-deps --entrypoint python iss-live -m app.nasa_media
docker compose up --detach --force-recreate --wait --wait-timeout 120 iss-live
docker exec astrolearner-iss-live python -m app.preflight
