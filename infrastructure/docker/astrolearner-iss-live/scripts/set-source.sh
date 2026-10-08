#!/usr/bin/env bash
set -euo pipefail

project_dir=/srv/data/compose/astrolearner-iss-live
env_file="${project_dir}/.env"

if [[ ! -f ${env_file} ]]; then
    echo "No existe ${env_file}" >&2
    exit 1
fi

read -r -p "URL directa HTTP(S)/HLS autorizada: " source_url
if [[ ! ${source_url} =~ ^https?://[^[:space:]]+$ ]]; then
    echo "URL no válida: debe empezar por http:// o https:// y no contener espacios" >&2
    exit 1
fi
if [[ ${source_url} =~ (^|//)(www\.)?(youtube\.com|youtu\.be)(/|$) ]]; then
    echo "No pegues una página de YouTube; se necesita la URL directa del proveedor" >&2
    exit 1
fi

read -r -p "Nombre/atribución de la fuente: " source_label
if [[ -z ${source_label} || ${source_label} == *$'\n'* ]]; then
    echo "La atribución no puede estar vacía" >&2
    exit 1
fi

backup="${env_file}.before-source-$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$(mktemp "${project_dir}/.env.source.XXXXXX")"
trap 'rm -f -- "${temporary}"' EXIT
cp -a -- "${env_file}" "${backup}"

awk -v url="${source_url}" -v label="${source_label}" '
    BEGIN { found_url = 0; found_label = 0 }
    /^ISS_LIVE_SOURCE_URL=/ {
        print "ISS_LIVE_SOURCE_URL=" url
        found_url = 1
        next
    }
    /^ISS_LIVE_SOURCE_LABEL=/ {
        print "ISS_LIVE_SOURCE_LABEL=" label
        found_label = 1
        next
    }
    { print }
    END {
        if (!found_url) print "ISS_LIVE_SOURCE_URL=" url
        if (!found_label) print "ISS_LIVE_SOURCE_LABEL=" label
    }
' "${env_file}" > "${temporary}"

chmod 600 "${temporary}"
mv -- "${temporary}" "${env_file}"
trap - EXIT

echo "Fuente guardada. Copia de seguridad: ${backup}"
echo "ISS_LIVE_DRY_RUN sigue sin modificarse; no se ha iniciado ninguna emisión."
echo "Para aplicar la configuración en simulación:"
echo "  cd ${project_dir}"
echo "  sudo docker compose up -d --build --wait --wait-timeout 180 iss-live"
