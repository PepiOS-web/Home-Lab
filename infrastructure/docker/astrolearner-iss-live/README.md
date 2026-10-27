# AstroLearner ISS Live

Servicio aislado para componer una emisión casi continua con una fuente de la
ISS, mapa orbital detallado y música ambiental procedural. Cada bloque dura 10 h 50 min,
se cierra, espera 90 segundos y crea una emisión nueva.

Los cortes de transporte antes de ese límite ya no crean vídeos nuevos:
se intenta reconectar a la misma emisión, con el mismo enlace y entrada RTMP.
La hora límite original no se reinicia al recuperar la conexión.

Mientras no exista una fuente directa autorizada, el servicio puede utilizar
imágenes recientes de la Tierra de NASA EPIC/DSCOVR. Estas imágenes se
descargan desde la API oficial, se atribuyen dentro del vídeo y se identifican
expresamente como imágenes recientes, no como una cámara en directo de la ISS.

## Seguridad y comportamiento inicial

- `ISS_LIVE_DRY_RUN=true` por defecto y bloquea toda emisión.
- Con dry-run desactivado, `ISS_LIVE_AUTO_START=false` evita emisiones tras un
  reinicio; el directo solo se inicia manualmente desde Homepage.
- Los controles web requieren un token aleatorio de al menos 32 caracteres la
  primera vez. Se intercambia por una sesión revocable de hasta 30 días en ese
  navegador; el token no se guarda en JavaScript ni en el almacenamiento web.
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

## Acceso recordado al control del directo

El portal comprueba la sesión al abrirse. Si ya está autorizada, oculta el campo
del token y permite usar los controles en otras pestañas del mismo navegador.
La autorización inicial sigue pidiendo el token; no existe acceso anónimo por
estar en LAN/Tailscale ni se inserta el secreto en HTML, Homepage o URLs.

La cookie independiente del token de Google usa `Secure`, `HttpOnly`,
`SameSite=Strict`, no define Domain y se limita a `/iss-live/control/`. Requiere
el portal HTTPS. Solo dura 30 días desde la autorización, sin renovación
automática. El backend comprueba además el origen exacto en todos los cambios.
La API con Bearer existente sigue disponible para operadores.

Solo se guardan hashes HMAC y caducidades en el archivo privado
`/srv/data/appdata/astrolearner-iss-live/music/.control-sessions.json`, con
escritura atómica y permisos `0600`. No contiene el token de control ni la cookie
en claro, no se sirve desde Homepage y admite como máximo 128 sesiones.
El reinicio conserva las sesiones. Rotar `ISS_LIVE_CONTROL_TOKEN` las invalida
todas. **Cerrar sesión** revoca esa sesión en el servidor, no solo la cookie,
y no detiene ni inicia ninguna emisión. Úsalo al terminar en equipos compartidos.

Una pestaña antigua que aún tenga el token en sessionStorage lo elimina e
intenta intercambiarlo una sola vez. Si las cookies están bloqueadas, no se
desbloquean los botones y se muestra un aviso, sin desactivar autenticación.

Cambios: `GET/POST /session` y `POST /session/logout` bajo el mismo proxy de
controles. No cambia Caddy, los puertos, OAuth, el encoder, FPS ni el autoarranque.
Un despliegue necesita recrear el servicio y debe hacerse con la emisión ya
detenida manualmente; nunca ejecutar una recreación durante un directo activo.

## Recuperación de cortes y rotación al límite

- Los nuevos directos usan `enableAutoStop=false`: una pérdida temporal de RTMP
  no debe cerrar automáticamente la emisión mientras el controlador reintenta.
- Ante `Broken pipe`, reset, timeout u otro error de transporte reconocido,
  se reinicia solo FFmpeg hacia el **mismo broadcast y stream**. No se vuelven a
  llamar a `liveBroadcasts.insert`, `liveStreams.insert` o `bind` para recuperar.
- Reintentos iniciales espaciados 5, 10, 15… hasta 30 s; tras unos dos minutos
  o 8 intentos se pasa a uno por minuto, siempre dentro del bloque original.
  La API comprueba que el vídeo sigue existiendo y mantiene su privacidad.
- Durante el corte el portal indica recuperación, conserva el enlace y no
  confirma música/fotogramas enviados mientras FFmpeg está detenido.
  `reconnect_count`, `last_reconnect_at` y `last_reconnect_reason` son datos
  públicos acotados, sin URL de ingestión, clave, IP ni error libre del proveedor.
- Se intenta retomar la música desde la última posición de medios codificada,
  no desde el reloj del corte. No cambia el WAV, volumen, lista ni bucle.
- Al llegar a `ISS_LIVE_BLOCK_SECONDS=39000` (10 h 50 min), incluso si se está
  esperando reconexión, se cierra ese bloque, se espera el intervalo configurado
  (`ISS_LIVE_GAP_SECONDS=90`) y se crea el siguiente. Reintentar nunca extiende
  ese límite ni incrementa el número de bloques creados.
- **Detener** cancela la espera/reconexión y cierra la emisión. Fallos de filtro,
  encoder o memoria no se disfrazan de red: se informa y detiene sin crear un
  bucle de vídeos nuevos. Tampoco se intenta reabrir un vídeo ya `complete`,
  revocado, inexistente o cuya privacidad haya cambiado.

Como el cierre automático de YouTube queda desactivado, una caída abrupta de
todo el servidor puede dejar el evento abierto sin señal: cerrar desde Studio
si el controlador no puede hacerlo. No se promete continuidad de imagen durante
una pérdida de conexión ni resucitar vídeos que YouTube ya dio por finalizados.

Prueba sin publicación: `python -m app.recovery_preflight` dentro de un contenedor
aislado con `--network none`, sin volúmenes ni credenciales. Utiliza únicamente
vídeo sintético pequeño a 30 FPS y dos receptores RTMP de loopback; mata el
primero y verifica recepción tras reconexión al mismo vídeo simulado, respetando
un límite de 24 s. No ejecuta el flujo de Google ni es un benchmark de la cámara.
El instalador del operador exige el directo detenido, conserva una imagen y
fuentes para recuperación, ejecuta esa prueba antes de recrear solo `iss-live`
y compara la configuración efectiva antes/después. No modifica `.env`, sesiones
web, OAuth, cámara, mapa, resolución, encoder, música o FPS.

## Multistream opcional: YouTube + Starvios

Starvios está desactivado si no existe configuración privada. No utiliza una
API de Starvios ni su sesión web: envía H.264/AAC al servidor RTMPS de Cloudflare
que proporciona su panel. No reutilizar una clave mostrada en capturas; regenerar
en Starvios antes de introducirla en el portal HTTPS.

Con la emisión detenida, en **Multistream · Starvios**, pegar la nueva clave,
confirmar su regeneración, marcar el envío adicional y **Guardar sin iniciar**.
Guardar nunca publica. **Iniciar emisión pública** inicia ambos destinos y
**Detener** detiene ambos. Desmarcar y guardar, con la emisión detenida, permite
volver a YouTube solamente sin borrar la clave. Dejar el campo de clave vacío
conserva la guardada; una nueva clave exige confirmar su regeneración. El servidor
es fijo (`rtmps://live.cloudflare.com:443/live/`), no una URL arbitraria del cliente.

La clave se guarda atómicamente con permisos `0600` en
`/srv/data/appdata/astrolearner-iss-live/music/.starvios.json`, fuera del proyecto,
del contexto Docker y del volumen público de estado. El API `GET /starvios` solo
devuelve si está configurada/habilitada; `POST /starvios` requiere el mismo token
o sesión y origen HTTPS exacto que el resto de controles. No hay lectura de clave
en el navegador, almacenamiento web, métricas, HTML ni errores. Un archivo privado
corrupto, enlazado simbólicamente o con permisos abiertos se rechaza. No incluirlo
en commits ni en copias públicas; los backups privados del servidor deben seguir
protegidos porque contienen credenciales. Los procesos FFmpeg usan argumentos
privados con los destinos, como la salida YouTube anterior: administradores del
host y Docker pueden inspeccionarlos. No publicar listados de procesos sin redactar.

Se codifica una vez y se distribuyen paquetes con `tee` + FIFO por destino.
Cada cola tiene 120 paquetes, descarta durante un atasco en lugar de bloquear al
encoder y espera un fotograma clave para reanudar. Reconecta cada 5 segundos,
sin límite de intentos dentro del bloque. `rw_timeout=15 s` acota operaciones de
red; `onfail=ignore` evita que el fallo permanente de una salida cierre la otra.
Al caer o saturarse una salida se pierden fotogramas allí, no se guarda una cola
ilimitada ni se promete ausencia de cortes. El proceso y la fuente siguen siendo
compartidos: una caída del encoder, del servidor o de la conexión común afecta
a ambos. Los errores RTMP se redactan para ambos destinos antes de guardarlos.

El perfil multistream requiere `libx264`, conserva resolución/FPS/bitrate/música
y añade CBR con relleno HRD, GOP cerrado de 2 s, sin B-frames. El envío a dos
plataformas necesita aproximadamente el doble de subida: con 4500k de vídeo y
128k de audio, unos 9,3 Mbps de medios agregados más sobrecarga y margen. Los
reintentos internos FIFO no incrementan `reconnect_count` del controlador, que
cuenta únicamente relanzamientos completos del proceso. La hora límite original
de 10h50 y pausa de 90 s siguen gobernando ambos envíos; en el nuevo bloque se crea
otro vídeo de YouTube y se reutiliza la entrada Starvios. Confirmar en su panel si
esa entrada sigue vigente. No se ha automatizado el título/categoría de Starvios
ni verificado sus límites de duración, permisos de simulcast o guardado de vídeos.

El portal muestra únicamente **salida local preparada, recepción SIN verificar**:
los fotogramas codificados no demuestran que Starvios los recibe. Comprobar en su
canal. Si YouTube revoca/cierra la emisión o falla una verificación crítica, el
controlador detiene el bloque completo; esto no ofrece dos emisoras independientes
del controlador de YouTube. Los títulos y descripciones existentes solo se aplican
a YouTube, los de Starvios se gestionan en su propia web.

Prueba aislada: `python -m app.multistream_preflight`, con `--network none`, sin
volúmenes ni credenciales. Usa dos receptores de loopback y vídeo sintético:
YouTube simulado arranca sin Starvios, ambos reciben, se corta cada receptor y
se comprueba que el otro sigue recibiendo y el cortado reconecta con el mismo
encoder. No publica ni mide la subida real o el rendimiento 720p del servidor.
El instalador `infrastructure/maintenance/install-live-multistream.sh` del
repositorio exige la recuperación anterior instalada, comprueba hashes,
requiere el directo detenido, conserva imagen/fuentes/configuración anteriores,
prueba ambos módulos de recuperación en Docker sin red externa y solo después
recrea `iss-live`. No recrea el navegador, no cambia `.env` ni inicia emisiones.

## Edición de metadatos de YouTube

En **Control del directo**, autoriza el navegador una vez y edita los campos:

- **Guardar para próximos directos** conserva los textos, sin iniciar ni
  modificar una emisión existente.
- **Actualizar directo actual** modifica la emisión gestionada por este
  controlador y guarda también los textos para las próximas. No reinicia FFmpeg
  ni cambia la privacidad, el horario o la clave de emisión.

Los valores sobreviven a recreaciones del contenedor en
`/srv/data/appdata/astrolearner-iss-live/music/live-metadata.json`, mediante
escritura atómica con permisos `0600`; no se publican como archivo estático.
El título admite 1–100 caracteres y la descripción hasta 5000 bytes UTF-8.
No se permiten los caracteres `<` y `>`. La descripción predeterminada aclara
que el material visual NASA es grabado cuando corresponde.

La lectura autenticada `GET /metadata` acepta la ausencia de Origin típica de
GET del mismo origen. Los cambios `POST /metadata` mantienen la comprobación
del origen exacto del portal y del token o sesión válida; se rechazan IDs de vídeo proporcionados
por el cliente. No hay guardado automático al escribir ni llamadas a Google
durante el refresco del panel. Si YouTube rechaza una actualización, se informa
del fallo, se conservan los textos para futuras emisiones y el vídeo sigue.

## Salud de la emisión y «Ahora suena»

El control del portal muestra comprobaciones independientes, también sin
desbloquear los controles:

- **Fotogramas del servidor**: última vez que aumentó el contador de FFmpeg.
  Más de 15 segundos sin avance se señala como posible bloqueo. La fecha de
  actualización general del panel no se usa para dar por sana la señal.
- **Entrada en YouTube**: ciclo y privacidad de la emisión, recepción de la
  entrada, evaluación de salud y códigos de avisos. Una consulta/evaluación con
  más de 150 segundos o sin fecha queda sin confirmar; `noData` no equivale
  por sí solo a que no esté llegando vídeo.
- **Posición ISS**: fecha orbital de la respuesta válida, no la hora de
  recepción HTTP. Más de 60 segundos se marca como información antigua;
  un error no rejuvenece la última posición.
- **Fuente visual base**: distingue la señal externa de cámara, los vídeos
  grabados y el mapa de respaldo. Solo afirma una fuente activa con un estado
  reciente y fotogramas de salida confirmados; tener una URL configurada no
  demuestra que esté emitiéndose. La señal externa necesita además fotogramas
  propios recientes. No muestra direcciones privadas ni errores libres.

El portal lee el estado local cada 3 segundos y **no consulta la API de
YouTube**. El controlador consulta ciclo y salud cada 60 segundos cuando la
emisión está confirmada, o cada 15 segundos durante su preparación. La lectura
de progreso continúa mientras Google responde, para no bloquear FFmpeg ni
producir alertas por la latencia de esa consulta. No se incorporan nuevos
reinicios automáticos por los avisos de salud.

«Ahora suena» identifica el tema y su posición dentro de la sesión de una hora
utilizando `out_time_us` de FFmpeg y el manifiesto JSON junto al WAV. No suma
tiempo de reloj ni simula reproducción cuando no hay emisión. El progreso
corresponde al envío y puede diferir de lo que oye un espectador por la latencia
de YouTube. El manifiesto se valida y carga una sola vez; si no existe o es
inválido, se mantiene la pista genérica sin inventar nombres/progreso de temas.

Solo se publican estados y códigos de avisos permitidos: no se exportan claves,
IDs privados de entrada, direcciones de ingestión ni descripciones libres de
la API. Se mantiene la autenticación del token y el montaje actual de vídeo.
Los vídeos NASA grabados se identifican como tales; el panel no los atribuye a
EPIC/DSCOVR cuando esa fuente no se muestra en la emisión.

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

### Cámara externa con respaldo automático — experimental y desactivada

El selector preparado añade una entrada externa de vídeo sin convertir los
cortes de esa entrada en emisiones nuevas de YouTube. Mantiene una sola salida
de vídeo y la música Lo-Fi: si faltan fotogramas de la cámara, selecciona el MP4
NASA descargado; si ese respaldo no puede leerse, utiliza el mapa orbital. Al
recuperarse la fuente externa, espera continuidad antes de volver a ella. El
seguimiento orbital se actualiza por separado de la cámara.

Esta capacidad **no aporta por sí misma una cámara ISS accesible ni derechos
de retransmisión**. Se necesita una URL directa suministrada o permitida por
el proveedor y comprobar sus condiciones. El OAuth de Google únicamente
autoriza la publicación en nuestro canal. No se extraen señales de páginas
YouTube ni se incorporan credenciales de terceros o técnicas de elusión.

Los valores iniciales son seguros y no alteran la fuente actual:

```dotenv
ISS_LIVE_CAMERA_ENABLED=false
ISS_LIVE_CAMERA_URL=
ISS_LIVE_CAMERA_AUTHORIZED=false
ISS_LIVE_CAMERA_MODE=auto
ISS_LIVE_CAMERA_TIMEOUT_SECONDS=8
ISS_LIVE_CAMERA_STABLE_SECONDS=15
ISS_LIVE_CAMERA_RETRY_SECONDS=30
```

`AUTHORIZED=true` es una declaración del operador de haber verificado el uso
permitido, no una verificación automática del origen o de sus licencias. No
cambiar estos valores hasta disponer de una fuente válida. La URL se conserva
solo en el `.env` privado, fuera de Git y del portal; no publicar archivos de
estado, registros o comandos que pudieran contener enlaces firmados.

Con el selector habilitado y configurado, el modo automático espera al menos
15 segundos de recepción estable para seleccionar la cámara. Sin fotogramas
durante 8 segundos, utiliza el respaldo y vuelve a intentar la conexión cada
30 segundos. Estos umbrales son configurables. La transición mantiene la misma
conexión de salida: no se cierra ni se crea una emisión por un corte de cámara,
y la música no se toma del proveedor externo.

Se comprueba la recepción de fotogramas, **no su luminosidad**: una escena negra
durante la noche orbital no debe provocar por sí sola un cambio. Tampoco se
puede identificar mediante este mecanismo si el proveedor está mostrando una
cámara real, una pausa o material grabado. La etiqueta «señal externa ISS» no
es una garantía de contenido en tiempo real; los respaldos propios se identifican
como grabados y el mapa se presenta como seguimiento orbital.

En el portal, «Fuente visual base» muestra el origen seleccionado, la fecha
del último fotograma de cámara y los cambios de fuente cuando está en respaldo.
Sin emisión, preparación incompleta o estado antiguo, no muestra una cámara
activa. Este panel solo lee el estado local; no añade consultas a Google ni
permite editar la URL o activar la cámara desde el navegador.
El mapa periódico se superpone a esa fuente base, como en el montaje anterior.
El transporte MJPEG de alta frecuencia se limita a conexiones de nombre local,
sin cabeceras de proxy ni peticiones de navegador entre sitios: no se expone
mediante el prefijo de controles del portal. Para la vista de pruebas se utiliza
el puerto de staging mediante túnel SSH, no una URL pública de Homepage.

Antes de producción debe probarse por separado con una fuente controlada:
arranque sin cámara, pérdida y recuperación, respaldo descargado ausente y
último recurso del mapa. Después hay que medir CPU, memoria y velocidad del
pipeline a **720p y 12 FPS**. El selector es experimental y consume recursos
adicionales; un preflight correcto de la configuración anterior no demuestra
capacidad para la nueva. No cambiar el encoder ni forzar una calidad mayor.
No recrear el contenedor de producción durante una emisión activa: preparar
los archivos no activa los cambios hasta un reinicio planificado.

### Prueba aislada sin YouTube

Hay un Compose separado, sin OAuth, token de control, autoarranque ni acceso
de escritura a los vídeos de producción. Publica únicamente el puerto local
`127.0.0.1:8094`, utiliza otra imagen y guarda sus datos en un tmpfs. No usa
el `.env` de producción:

```bash
cd /srv/data/compose/astrolearner-iss-live
sudo docker compose --env-file camera-staging.env.example \
  -f compose.camera-staging.yaml up -d --build --wait --wait-timeout 180
curl -fsS http://127.0.0.1:8094/api/status | python3 -m json.tool
```

Sin una cámara configurada solo selecciona vídeos de respaldo o mapa. La vista
de prueba es `http://127.0.0.1:8094/video.mjpeg`; no crea emisiones. Para verla
desde Windows puede abrirse un túnel `ssh -L 8094:127.0.0.1:8094 homelab`.
Para ensayar una fuente autorizada posteriormente, copiar el ejemplo a
`.env.camera-staging` (excluido de Git), editarlo de forma privada y pasar ese
archivo en `--env-file`. No mostrar `docker compose config` sin `--quiet`,
pues puede imprimir la URL privada de la cámara.

El comprobador autocontenido de cortes no carga la configuración, las claves
ni la cámara real. Genera señales locales de colores, un vídeo temporal y audio
AAC, corta/restablece la fuente y comprueba un único archivo de salida continuo:

```bash
sudo docker compose --env-file camera-staging.env.example \
  -f compose.camera-staging.yaml exec camera-staging \
  python -m app.camera_preflight --width 1280 --height 720
```

También puede ejecutarse con Python y FFmpeg locales, sin Docker:
`python -m app.camera_preflight --ffmpeg /ruta/ffmpeg`. Sus tiempos reducidos
son exclusivos de la simulación: no cambian los umbrales de producción. Pasar
esta prueba acredita continuidad ante esos cortes simulados, **no** identifica
la cámara real ni garantiza capacidad bajo carga en el servidor. No ejecutar
pruebas de carga adicionales mientras el directo ya presente problemas de
recepción. Para detener solo las pruebas:

```bash
sudo docker compose --env-file camera-staging.env.example \
  -f compose.camera-staging.yaml down
```

### Captura autorizada del reproductor — preparación aislada

El operador confirmó disponer de permiso de retransmisión. Esto no convierte el
reproductor del portal en una entrada de FFmpeg: el nuevo sidecar abre una página
**dedicada solo al vídeo** en Chrome dentro del servidor. Nunca captura Homepage,
controles, tokens o el escritorio de Windows. No depende de que el ordenador del
usuario esté encendido. No extrae URLs de Googlevideo, cookies ni sesiones ajenas.

La página utiliza el reproductor oficial y su IFrame API, sin credenciales de
Google. Lo silencia para conservar la música Lo-Fi del montaje. Solo ofrece JPEG
cuando el reproductor está reproduciendo y avanzan tanto el tiempo como los
fotogramas decodificados. Una pausa, error, anuncio o bloqueo deja de ofrecer
fotogramas: el selector utiliza los vídeos locales y, si faltan, el mapa. Negro
durante noche orbital no es fallo. El proveedor puede emitir material grabado;
la captura no puede certificar que toda imagen corresponda a una cámara en vivo.

El sidecar no monta datos, OAuth, claves RTMP, el socket Docker ni el portal.
Mantiene sandbox de Chromium, usuario `pwuser`, raíz de solo lectura, capacidades
eliminadas y límites de CPU/RAM/PID. No abre un puerto de producción al host.
La prueba expone solo `127.0.0.1:8095`. No usar `--no-sandbox`, `--privileged`,
`SYS_ADMIN`, `ipc: host` ni desactivar AppArmor del host para hacerlo arrancar.
Si el sandbox no es compatible, detener la prueba y revisar el diagnóstico.

Playwright está fijado a 1.63.0, con imagen por digest y dependencias por hash.
Chrome 155.0.8059.79 se instala solo dentro de esa imagen, desde el paquete
oficial de Google validado por SHA-256, para disponer de códecs H.264/AAC.
El perfil seccomp está derivado del de Microsoft Playwright, commit
`ccd519ec3de6bf3f1339499fb234f5e969b33844`, archivo
`utils/docker/seccomp_profile.json`; SHA-256 del original
`cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.
Se conserva su licencia en `camera-browser-LICENSE`. La copia local mantiene
`clone3` denegado con `ENOSYS` para permitir el fallback de glibc y permite la
llamada `chroot` usada por el sandbox dentro de su espacio de nombres. El kernel
sigue exigiendo la capacidad correspondiente; no se añaden capacidades al
contenedor. Véase `BROWSER-CAMERA.md`. Estas adaptaciones solo se aplican al
sidecar: no modifican los servicios existentes ni las protecciones del host.

Primero debe detenerse el directo mediante el portal. El script **no lo detiene
por su cuenta** y cancela la prueba si producción sigue solicitando emisión.
La captura supone carga adicional: no aprobarla a partir de las pruebas unitarias
ni de haber visto el reproductor en Windows.

```bash
cd /srv/data/compose/astrolearner-iss-live
# .env.camera-browser es privado, separado del .env de producción.
# Confirmar ISS_BROWSER_CAPTURE_AUTHORIZED=true únicamente con permiso de uso.
sudo ./scripts/test-browser-camera.sh
```

El script construye solo imágenes de prueba, espera vídeo real, genera una salida
H.264/AAC **local** de 100 segundos, corta y recupera el sidecar y exige ver
`camera → recorded → camera`. Comprueba 720p/12 FPS de salida, ritmo de captura,
tiempo de procesamiento, fotogramas perdidos y ausencia de silencios en su tono
de prueba. El audio de prueba no sustituye la lista musical de producción.
Los archivos de vídeo/audio temporales se borran al finalizar y los contenedores
de prueba se detienen; no se publican vídeos ni se altera el directo anterior.

Un resultado fallido no autoriza activar producción. `compose.camera-browser-live.yaml`
es un **opt-in posterior** que conecta la salida MJPEG interna al selector y mantiene
la música, mapa periódico, etiquetas, controles y encoder actuales. No se aplica
automáticamente. Tras revisar un resultado satisfactorio hay que hacer un despliegue
planificado; recrear el contenedor de producción corta una emisión que esté activa.

La carpeta de staging no contiene OAuth y no debe añadirse a ella. Mantener el
permiso en `.env.camera-browser`, excluido de Git; no mostrar un `compose config`
sin `--quiet` cuando se mezcle con el `.env` de producción.

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
