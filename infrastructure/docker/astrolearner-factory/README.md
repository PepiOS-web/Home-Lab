# AstroLearner Factory

MVP local para convertir fuentes científicas verificables en un borrador de
vídeo de AstroLearner. No utiliza APIs de IA de pago y no publica contenido.

## Alcance de esta primera versión

El flujo implementado es:

```text
tema + 1-5 fuentes permitidas
        |
        v
captura de fuentes -> guion JSON + prompts de escena mediante Ollama -> revisión humana
        |                                                     |
        |                                          clips IA opcionales importados
        |
        v
Piper TTS -> clips breves opcionales + ilustraciones Pillow + música original
        -> vídeo largo + 3 Shorts existentes + Short literal derivado + SRT
        |
        v
revisión humana -> borrador aprobado (sin subida ni publicación)
```

Componentes:

- Ollama local con `qwen3.5:4b-q4_K_M`.
- FastAPI y SQLite para el panel, cola secuencial y trazabilidad.
- Piper con la voz española `es_ES-davefx-medium`.
- FFmpeg y Pillow para generar ilustraciones científicas originales, música
  ambiental procedural, el vídeo 16:9, los tres Shorts 9:16 existentes con
  ángulos distintos, subtítulos y miniatura. En vídeos de 120 segundos o más,
  intenta añadir por separado un Short vertical con un fragmento continuo
  literal del guion largo; no sustituye a los tres Shorts actuales.
- Ollama genera un `video_prompt_en` opcional por segmento. El usuario puede
  pegarlo en un generador externo y subir manualmente un MP4 H.264 de 1–20 s.
  Los clips son inserciones visuales opcionales; si no hay clip, se conserva el
  render procedural actual. No existe dependencia de APIs o servicios externos.
  La demo oficial de [LTX-2.3 en Hugging Face](https://huggingface.co/spaces/Lightricks/LTX-2-3)
  es externa; disponibilidad, límites y condiciones pueden cambiar. El Factory
  no depende de ella y exige revisar la licencia vigente antes de publicar clips.

La aplicación descarga únicamente páginas HTTPS de una lista explícita de
dominios científicos. Trata todo el texto descargado como datos no fiables y
no como instrucciones. El render no descarga fotos ni música de terceros:
elige un renderizador cerrado (fases lunares, órbitas, eclipses, planetas,
estrellas, galaxias, telescopios o escalas) y genera tanto la ilustración como
la música dentro del contenedor. Los esquemas no pretenden estar a escala.

## Recursos y privacidad

- Interfaz enlazada solo a `127.0.0.1:8090`.
- Formularios protegidos con token anti-CSRF y cabeceras de navegador
  restrictivas.
- Ollama no publica ningún puerto y tiene desactivadas las funciones cloud.
- Un único trabajo se procesa a la vez.
- Ollama se limita a 5 GiB y descarga el modelo de memoria tras la doble pasada.
- Cada borrador pasa por una segunda revisión local que corrige contradicciones,
  términos impropios y afirmaciones sin respaldo antes de mostrarse.
- El estudio se limita a 2 GiB y cuatro CPU lógicas.
- Datos persistentes: `/srv/data/appdata/astrolearner`.
- No hay claves, credenciales ni tokens en el repositorio.
- Un reinicio marca los trabajos interrumpidos como fallidos para que puedan
  reintentarse en lugar de quedar bloqueados.

La imagen de Ollama está fijada al manifiesto Linux/amd64 que fue auditado al
crear este MVP. Las actualizaciones deben probarse de forma explícita.

## Instalación controlada

Copiar el directorio a `/srv/data/compose/astrolearner-factory` y ejecutar:

```bash
cd /srv/data/compose/astrolearner-factory
cp .env.example .env
chmod 600 .env
./scripts/doctor.sh
sudo ./scripts/bootstrap.sh
```

`doctor.sh` es de solo lectura. `bootstrap.sh` crea exclusivamente los
directorios de AstroLearner, construye la imagen local, descarga el modelo y la
voz, y levanta los dos contenedores.

## Prueba aislada de cambios

Para probar una versión nueva sin reemplazar `astrolearner-factory` ni mezclar
trabajos con sus datos, el repositorio incluye `compose.staging.yaml`. Levanta
solo un contenedor de estudio con nombre y puerto propios, y guarda sus trabajos
en `runtime/` dentro de la carpeta de staging. Reutiliza el Ollama
existente y monta su voz en solo lectura; por tanto, una generación de prueba
puede ocupar temporalmente la cola/CPU del Ollama de producción.

En el servidor, después de copiar la rama de prueba a un directorio separado:

```bash
cd /srv/data/compose/astrolearner-factory-staging
cp staging.env.example .env.staging
sudo docker inspect --format='{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{println}}{{end}}' astrolearner-ollama
```

Pon en `ASTRO_SHARED_NETWORK` de `.env.staging` el nombre de red que devolvió
el último comando. Verifica también que `ASTRO_STAGING_PORT` no esté ocupado y
que `ASTRO_MODEL` coincida con el modelo ya descargado y `PUID`/`PGID` con el
usuario del contenedor actual. No copies el `.env` de producción; el fichero de
staging solo contiene configuración local y queda excluido del build. Crea solo
el directorio nuevo de staging:

```bash
mkdir -m 750 runtime
sudo docker compose --project-name astrolearner-factory-staging \
  --env-file .env.staging -f compose.staging.yaml \
  up -d --build --wait --wait-timeout 180 studio
curl -fsS http://127.0.0.1:8091/health
```

Abre el panel por un túnel SSH con `ssh -L 8091:127.0.0.1:8091 homelab` y
visita `http://127.0.0.1:8091`. Crea un trabajo de al menos dos minutos, revisa
que el borrador traiga prompts de escena, sube un MP4 opcional antes de aprobar,
y comprueba el vídeo largo, los tres Shorts existentes y el Short derivado si
hay un fragmento válido. Para cerrar solo el contenedor de prueba, usa
`docker compose` con los mismos argumentos y `down`; los archivos de staging
se conservan. No uses `down --volumes` ni borres la carpeta de datos.

Para abrir el panel desde Windows sin modificar Caddy o DNS:

```powershell
ssh -L 8090:127.0.0.1:8090 homelab
```

Mientras esa sesión permanezca abierta, visitar
`http://127.0.0.1:8090` en el navegador.

## Uso

1. Introducir un tema concreto y entre una y cinco URLs permitidas.
2. Esperar la generación local. En CPU puede tardar varios minutos.
3. Contrastar manualmente cada afirmación con las fuentes mostradas.
4. Corregir títulos, narración, descripción o advertencias desde el editor.
5. Si se quiere, copiar el prompt de una escena, generar el clip fuera del
   servidor y subirlo antes de aprobar el guion. Las subidas se limitan a 80 MiB
   por clip y 256 MiB en total por trabajo; se validan con `ffprobe` y no se
   aceptan URLs ni listas de reproducción.
6. Aprobar el guion para iniciar el TTS y render, o rechazarlo sin borrar la
   trazabilidad.
7. Ver completos el vídeo largo, los tres Shorts existentes y el Short derivado
   cuando esté disponible antes de aprobar el borrador.
8. Si se actualiza el motor visual o la mezcla, usar `Volver a renderizar` sin
   regenerar el guion.

Estados principales:

```text
queued -> processing -> script_ready -> queued -> processing
       -> review_required -> approved
```

Un error deja el trabajo en `failed` y permite reintentar la etapa. La base de
datos utiliza WAL y los artefactos se escriben dentro del directorio UUID de
cada trabajo.

## Operación

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 studio
sudo docker compose logs --tail=100 ollama
./scripts/smoke-test.sh
sudo docker compose stop
```

Para eliminar solo los contenedores conservando modelos y trabajos:

```bash
sudo docker compose down
```

No ejecutar `down --volumes` ni borrar `/srv/data/appdata/astrolearner` si se
quieren conservar los resultados.

## Licencias y uso comercial

- Qwen3.5 se distribuye bajo Apache-2.0 según su ficha oficial.
- Piper se ejecuta como dependencia GPL-3.0.
- La ficha de `es_ES-davefx-medium` declara CC0 para el dataset de voz.
- Los clips MP4 aportados por el usuario quedan guardados dentro del trabajo y
  se registran en `licenses.json`; hay que comprobar la licencia del generador
  externo y la necesidad de declarar contenido sintético antes de publicar.
- Las ilustraciones y la música de esta versión son originales y se generan
  localmente. `licenses.json` registra el renderizador, la semilla de la música
  y confirma que no se usaron activos de terceros.

Antes de una publicación real siguen siendo obligatorias la revisión humana de
diagramas, voz, mezcla y subtítulos, las pruebas de originalidad, OAuth de
YouTube y una primera subida privada. La publicación pública seguirá siendo
una acción humana.
