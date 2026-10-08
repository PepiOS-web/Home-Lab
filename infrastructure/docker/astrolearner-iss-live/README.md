# AstroLearner ISS Live

Servicio aislado para componer una emisión casi continua con una fuente de la
ISS, mapa orbital detallado y música ambiental procedural. Cada bloque dura 10 h 50 min,
se cierra, espera 90 segundos y crea una emisión nueva.

Mientras no exista una fuente directa autorizada, el servicio puede utilizar
imágenes recientes de la Tierra de NASA EPIC/DSCOVR. Estas imágenes se
descargan desde la API oficial, se atribuyen dentro del vídeo y se identifican
expresamente como imágenes recientes, no como una cámara en directo de la ISS.

## Seguridad y comportamiento inicial

- `ISS_LIVE_DRY_RUN=true` por defecto y bloquea toda emisión.
- Con dry-run desactivado, `ISS_LIVE_AUTO_START=false` evita emisiones tras un
  reinicio; el directo solo se inicia manualmente desde Homepage.
- Los controles web requieren un token aleatorio de al menos 32 caracteres;
  solo se conserva en la sesión de la pestaña y nunca se muestra en el portal.
- No se monta `/dev/snd`; el contenedor no puede capturar un micrófono.
- La única entrada de audio es un WAV lo-fi procedural creado localmente, con
  teclado eléctrico, bajo y pulso muy suaves; sin ruido blanco, micrófono ni
  audio de los vídeos NASA.
- Música ambiental mezclada a nivel de fondo (sin micrófono ni audio de los vídeos NASA).
- El mapa de seguimiento incluye fronteras y costas Natural Earth 1:10m, además
  de la trayectoria reciente y los datos de posición de la ISS.
- Cliente OAuth, token y URL de la fuente no se almacenan en Git.
- API enlazada exclusivamente a `127.0.0.1:8092`.
- Contenedor sin capacidades, con raíz de solo lectura y límites de CPU/RAM.
- La imagen de estado se publica mediante un volumen de solo lectura en Homepage.
- La API solo se publica en el loopback del servidor (`127.0.0.1:8092`).
- Los paquetes Python quedan fijados mediante hashes y se auditan antes de desplegar.
- `.env`, secretos y copias de seguridad están excluidos del contexto Docker.
- El endpoint de control solo acepta operaciones POST desde el origen HTTPS
  del portal y valida el token en tiempo constante.
- El servicio principal solo monta las carpetas de música, caché NASA, estado y
  el token OAuth imprescindible; no dispone del secreto del cliente OAuth.

## Preparación

```bash
cd /srv/data/compose/astrolearner-iss-live
cp .env.example .env
chmod 600 .env
mkdir -p /srv/data/appdata/astrolearner-iss-live/{music,secrets,status}
touch /srv/data/appdata/astrolearner-iss-live/secrets/youtube-client-secret.json
chmod 700 /srv/data/appdata/astrolearner-iss-live/secrets
chmod 600 /srv/data/appdata/astrolearner-iss-live/secrets/youtube-client-secret.json
sudo docker compose up -d --build --wait
```

En el homelab preparado por este repositorio, el despliegue inicial y la
recreación de Homepage se realizan con una única orden:

```bash
sudo /srv/data/compose/astrolearner-iss-live/scripts/deploy.sh
```

Comprobar el modo seguro:

```bash
curl -fsS http://127.0.0.1:8092/api/status | python3 -m json.tool
sudo docker compose logs --tail=50
```

## Activación futura de YouTube

Hace falta crear unas credenciales OAuth de tipo aplicación de escritorio en
Google Cloud, habilitar YouTube Data API v3 y realizar una autorización humana
una sola vez. Primero se probará con `ISS_LIVE_PRIVACY=unlisted`. No cambiar
`ISS_LIVE_DRY_RUN=false` hasta que exista una fuente directa y autorizada y se
haya completado esa prueba privada.

Después de colocar el JSON descargado en
`/srv/data/appdata/astrolearner-iss-live/secrets/youtube-client-secret.json`,
abrir desde Windows un túnel independiente:

```powershell
ssh -L 8093:127.0.0.1:8093 homelab
```

En otra terminal del servidor, iniciar el asistente y abrir en el navegador la
URL que muestre:

```bash
cd /srv/data/compose/astrolearner-iss-live
sudo docker compose --profile tools run --rm --service-ports authorize
```

El token resultante queda en el directorio privado `secrets` y nunca se muestra
en Homepage ni se incluye en una imagen Docker.

`ISS_LIVE_SOURCE_URL` debe ser una entrada directa HTTP(S)/HLS autorizada. Una
página `youtube.com/watch` no es una entrada de vídeo y no debe colocarse ahí.

## Configurar la fuente visual

El único campo que debe modificarse cuando el proveedor entregue una fuente
directa autorizada es este, dentro del archivo `.env`:

```dotenv
ISS_LIVE_SOURCE_URL=https://proveedor.example/directo/playlist.m3u8
ISS_LIVE_SOURCE_LABEL=Nombre y atribución indicados por el proveedor
```

No se debe pegar una página de reproducción de YouTube. El programa acepta
exclusivamente una URL directa HTTP(S), como un manifiesto HLS `.m3u8` o una
fuente MJPEG. Primero se conserva `ISS_LIVE_DRY_RUN=true`; posteriormente se
realiza una prueba privada con un solo bloque antes de cualquier activación.

La fuente visual segura incluida se sirve localmente en
`http://127.0.0.1:8092/earth.mjpeg`. El reproductor oficial de NASA permanece
separado, insertado en Homepage, y no se retransmite dentro del canal.

La biblioteca curada de vídeos se descarga exclusivamente desde
`images-assets.nasa.gov`, prefiere la variante NASA `~large.mp4` (y usa `~medium.mp4`
como alternativa antes del máster original),
valida el centro de procedencia JSC, impone límites
de 20 GiB por archivo, comprueba cada archivo con `ffprobe` y registra su
SHA-256. Antes de emitir, los clips se normalizan y concatenan en un único MP4
H.264 720p12, sin audio. El directo hace loop sobre ese archivo único en lugar
de cambiar entre archivos NASA de parámetros distintos; el preparador ejecuta
el preflight atravesando el final y el reinicio del loop antes de permitir el
arranque manual. La salida está configurada inicialmente a 720p12 para
mantener una codificación estable en el servidor. Se activa
con `ISS_LIVE_USE_NASA_PLAYLIST=true` y se prepara mediante:

```bash
sudo /srv/data/compose/astrolearner-iss-live/scripts/download-nasa-media.sh
```

El audio original de esos vídeos no se incorpora a la emisión. Solo se usa la
música procedural creada localmente.

La imagen Docker incluye el controlador VAAPI Intel iHD (`intel-media-va-driver`)
y el servicio recibe solo el nodo de render Intel `/dev/dri/renderD128` (grupo
`render`, GID 993). Para
probar codificación H.264 por GPU sin iniciar un directo, establece
`ISS_LIVE_ENCODER=h264_vaapi`, recrea el servicio y ejecuta
`sudo docker exec astrolearner-iss-live python -m app.preflight`. El valor
predeterminado continúa siendo `libx264`; no cambies el encoder de producción
hasta que el preflight supere 1,05x en tiempo real. La ruta de hardware
procesa 720p a 12 fps con un límite de tres CPU (el servidor tiene cuatro
nucleos físicos). El preflight mide
decodificación acelerada y el pipeline completo a velocidad máxima, sin
contar el limitador `-re` usado durante la emisión.

La cartografía usa el conjunto Natural Earth 1:10m Admin 0 Countries
([fuente del conjunto](https://github.com/nvkelso/natural-earth-vector)); sus
geometrías están incluidas en la imagen Docker para no depender de un servicio
de mapas externo ni descargar mosaicos en directo.

Como alternativa a editar `.env`, ejecutar el asistente y pegar la URL cuando
la solicite:

```bash
/srv/data/compose/astrolearner-iss-live/scripts/set-source.sh
```
